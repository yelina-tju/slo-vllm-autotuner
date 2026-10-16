#!/usr/bin/env python3
"""Summarize oracle and one-factor controller ablation experiments."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


PHASE_BOUNDARIES = {
    "mixed_80_20": 60.0,
    "balanced": 210.0,
}


def load_complete_results(directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((directory / "trace_manifest.json").read_text(encoding="utf-8"))
    results = []
    for mode in manifest["config"]["modes"]:
        path = directory / mode["name"] / "result.json"
        if not path.exists():
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("status") != "complete":
            raise ValueError(f"incomplete result: {path}")
        if result.get("run_key") != manifest["run_key"]:
            raise ValueError(f"run-key mismatch: {path}")
        if len(result.get("requests", [])) != len(manifest["trace"]):
            raise ValueError(f"request-count mismatch: {path}")
        results.append(result)
    return manifest, results


def transition_delays(result: dict[str, Any]) -> dict[str, float | None]:
    delays: dict[str, float | None] = {
        "mixed_detection_delay_s": None,
        "balanced_detection_delay_s": None,
    }
    for execution in result["executions"]:
        target = execution["target_policy"]
        profile = "mixed_80_20" if target.startswith("mixed_80_20:") else "balanced"
        key = "mixed_detection_delay_s" if profile == "mixed_80_20" else "balanced_detection_delay_s"
        if delays[key] is None:
            delays[key] = execution["started_offset_s"] - PHASE_BOUNDARIES[profile]
    return delays


def decision_guard_counts(mode_dir: Path) -> dict[str, int]:
    counts = {
        "confirmation_wait_decisions": 0,
        "restart_cooldown_block_decisions": 0,
        "distance_hysteresis_block_decisions": 0,
        "rollback_decisions": 0,
    }
    path = mode_dir / "gateway_audit.jsonl"
    if not path.exists():
        return counts
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            if event.get("kind") != "decision":
                continue
            payload = event["payload"]
            reason = payload.get("reason", "")
            if "awaiting confirmation" in reason:
                counts["confirmation_wait_decisions"] += 1
            if "restart cooldown is active" in reason:
                counts["restart_cooldown_block_decisions"] += 1
            if reason == "active profile retained by distance/hysteresis":
                detector = payload.get("detector") or {}
                if detector.get("best_profile") != payload.get("active_profile"):
                    counts["distance_hysteresis_block_decisions"] += 1
            if payload.get("action") == "rollback":
                counts["rollback_decisions"] += 1
    return counts


def summarize(
    directory: Path,
    extra_directories: tuple[Path, ...] = (),
) -> dict[str, Any]:
    manifest, results = load_complete_results(directory)
    for extra_directory in extra_directories:
        extra_manifest, extra_results = load_complete_results(extra_directory)
        if extra_manifest["trace_sha256"] != manifest["trace_sha256"]:
            raise ValueError(f"trace mismatch: {extra_directory}")
        results.extend(extra_results)
    horizon = float(manifest["phases"][-1]["end_s"])
    absolute_upper_goodput = len(manifest["trace"]) / horizon
    rows = []
    for result in results:
        summary = result["summary"]
        counts = summary["status_counts"]
        rows.append({
            "mode": result["mode"]["name"],
            "attempted": summary["attempted"],
            "completed": summary["completed"],
            "slo_compliant": summary["slo_compliant"],
            "goodput_rps": summary["request_goodput"],
            "absolute_upper_gap_rps": absolute_upper_goodput - summary["request_goodput"],
            "http_429": counts.get("429", 0),
            "http_503": counts.get("503", 0),
            "completed_but_late": summary["completed"] - summary["slo_compliant"],
            "restart_count": result["restart_count"],
            "transition_duration_s": result["transition_duration_s"],
            "tail_violation_area_s": result["tail_violation_area_s"],
            "class_windows_without_success": result["class_windows_without_success"],
            "balanced_before_goodput_rps": result["by_phase"]["balanced_before"]["request_goodput"],
            "mixed_shift_goodput_rps": result["by_phase"]["mixed_shift"]["request_goodput"],
            "balanced_return_goodput_rps": result["by_phase"]["balanced_return"]["request_goodput"],
            **transition_delays(result),
            **decision_guard_counts(
                next(
                    candidate / result["mode"]["name"]
                    for candidate in (directory, *extra_directories)
                    if (candidate / result["mode"]["name"]).exists()
                )
            ),
        })

    by_mode = {row["mode"]: row for row in rows}
    full = by_mode.get("full_controller")
    oracle = by_mode.get("oracle_boundary")
    ablations = {}
    if full is not None:
        for name, row in by_mode.items():
            if not name.startswith("no_"):
                continue
            ablations[name] = {
                "goodput_gain_when_removed_rps": row["goodput_rps"] - full["goodput_rps"],
                "compliant_gain_when_removed": row["slo_compliant"] - full["slo_compliant"],
                "rejection_change_when_removed": (
                    row["http_429"] + row["http_503"]
                    - full["http_429"] - full["http_503"]
                ),
                "tail_area_change_when_removed_s": (
                    row["tail_violation_area_s"] - full["tail_violation_area_s"]
                ),
                "restart_change_when_removed": row["restart_count"] - full["restart_count"],
            }

    oracle_comparison = None
    if full is not None and oracle is not None:
        oracle_comparison = {
            "full_minus_oracle_goodput_rps": full["goodput_rps"] - oracle["goodput_rps"],
            "full_minus_oracle_compliant": full["slo_compliant"] - oracle["slo_compliant"],
            "full_minus_oracle_rejections": (
                full["http_429"] + full["http_503"]
                - oracle["http_429"] - oracle["http_503"]
            ),
            "extra_mixed_detection_delay_s": (
                full["mixed_detection_delay_s"] - oracle["mixed_detection_delay_s"]
            ),
            "extra_balanced_detection_delay_s": (
                full["balanced_detection_delay_s"] - oracle["balanced_detection_delay_s"]
            ),
        }

    return {
        "trace_sha256": manifest["trace_sha256"],
        "trace_requests": len(manifest["trace"]),
        "horizon_s": horizon,
        "absolute_perfect_service_upper_goodput_rps": absolute_upper_goodput,
        "completed_modes": len(rows),
        "modes": rows,
        "full_vs_boundary_oracle": oracle_comparison,
        "one_factor_ablations_vs_full": ablations,
        "interpretation_limits": [
            "oracle_boundary knows phase boundaries but still pays measured single-GPU transition cost",
            "the absolute upper bound assumes every arrival completes within SLO and is not achievable evidence",
            "one seed and serial execution do not establish statistical significance",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--extra-directory", type=Path, action="append", default=[])
    args = parser.parse_args()
    payload = summarize(args.directory, tuple(args.extra_directory))
    (args.directory / "ablation_analysis.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    rows = payload["modes"]
    if rows:
        with (args.directory / "ablation_summary.csv").open(
            "w", encoding="utf-8", newline=""
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
