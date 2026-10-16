#!/usr/bin/env python3
"""Aggregate paired multi-seed asymmetric-recovery experiments.

The random seed, rather than each request, is the experimental unit.  Raw
paired differences are retained so a small number of seeds is not presented as
spurious request-level statistical certainty.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import fmean, stdev


MODES = ("asymmetric_controller", "legacy_symmetric")
RETURN_PHASE = "balanced_return"


def status_count(summary: dict, code: int) -> int:
    counts = summary.get("status_counts", {})
    return int(counts.get(str(code), counts.get(code, 0)))


def first_transition_delay(result: dict, target_fragment: str, boundary_s: float):
    starts = [
        float(item["started_offset_s"])
        for item in result.get("executions", [])
        if target_fragment in str(item.get("target_policy", ""))
        and float(item["started_offset_s"]) >= boundary_s
    ]
    return None if not starts else min(starts) - boundary_s


def extract_metrics(result: dict, boundaries: dict[str, float]) -> dict:
    summary = result["summary"]
    return_summary = result["by_phase"][RETURN_PHASE]
    return {
        "goodput_rps": float(summary["request_goodput"]),
        "slo_compliant": int(summary["slo_compliant"]),
        "http_429": status_count(summary, 429),
        "http_503": status_count(summary, 503),
        "restart_count": int(result["restart_count"]),
        "transition_duration_s": float(result["transition_duration_s"]),
        "tail_violation_area_s": float(result["tail_violation_area_s"]),
        "class_windows_without_success": int(result["class_windows_without_success"]),
        "mixed_detection_delay_s": first_transition_delay(
            result, "mixed_80_20", boundaries["mixed_shift"]
        ),
        "return_recovery_delay_s": first_transition_delay(
            result, "balanced:", boundaries[RETURN_PHASE]
        ),
        "return_goodput_rps": float(return_summary["request_goodput"]),
        "return_slo_compliant": int(return_summary["slo_compliant"]),
        "return_http_429": status_count(return_summary, 429),
        "return_http_503": status_count(return_summary, 503),
    }


def summarize_values(values: list[float]) -> dict:
    return {
        "mean": fmean(values),
        "sample_stdev": stdev(values) if len(values) > 1 else None,
        "min": min(values),
        "max": max(values),
    }


def load_pair(directory: Path) -> dict:
    manifest = json.loads((directory / "trace_manifest.json").read_text(encoding="utf-8"))
    config = manifest["config"]
    seed = int(config["seed"])
    phases = manifest["phases"]
    boundaries = {phase["name"]: float(phase["start_s"]) for phase in phases}
    results = {}
    for mode in MODES:
        path = directory / mode / "result.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("status") != "complete":
            raise ValueError(f"incomplete result: {path}")
        if result.get("run_key") != manifest.get("run_key"):
            raise ValueError(f"run-key mismatch: {path}")
        if len(result.get("requests", [])) != len(manifest["trace"]):
            raise ValueError(f"unpaired request count: {path}")
        results[mode] = extract_metrics(result, boundaries)
    return {
        "seed": seed,
        "trace_sha256": manifest["trace_sha256"],
        "metrics": results,
    }


def analyze(directories: list[Path]) -> dict:
    pairs = sorted((load_pair(path) for path in directories), key=lambda item: item["seed"])
    seeds = [pair["seed"] for pair in pairs]
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"duplicate seeds: {seeds}")
    metric_names = list(pairs[0]["metrics"][MODES[0]])
    mode_summaries = {}
    for mode in MODES:
        mode_summaries[mode] = {}
        for metric in metric_names:
            available = [
                float(pair["metrics"][mode][metric])
                for pair in pairs
                if pair["metrics"][mode][metric] is not None
            ]
            mode_summaries[mode][metric] = (
                None if not available else summarize_values(available)
            )
    differences = {}
    for metric in metric_names:
        raw = []
        for pair in pairs:
            left = pair["metrics"][MODES[0]][metric]
            right = pair["metrics"][MODES[1]][metric]
            raw.append(None if left is None or right is None else left - right)
        available = [float(value) for value in raw if value is not None]
        legacy_mean = mode_summaries[MODES[1]][metric]
        mean_difference = None if not available else fmean(available)
        relative = None
        if legacy_mean is not None and legacy_mean["mean"] != 0 and mean_difference is not None:
            relative = mean_difference / legacy_mean["mean"]
        differences[metric] = {
            "asymmetric_minus_legacy_by_seed": dict(zip(map(str, seeds), raw)),
            "summary": None if not available else summarize_values(available),
            "relative_to_legacy_mean": relative,
        }
    return {
        "schema_version": 1,
        "experimental_unit": "paired random seed",
        "seed_count": len(pairs),
        "seeds": seeds,
        "pairs": pairs,
        "mode_summaries": mode_summaries,
        "paired_differences": differences,
        "interpretation_guardrails": [
            "Positive goodput/compliance deltas favor asymmetric recovery.",
            "Negative rejection, delay, restart, and violation deltas favor asymmetric recovery.",
            "With few seeds, report paired effects and dispersion; do not treat requests as independent replicates.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = analyze(args.directories)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["paired_differences"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
