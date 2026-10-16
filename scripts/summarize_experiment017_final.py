#!/usr/bin/env python3
"""Validate and aggregate the Experiment 017 Qwen2.5-7B final benchmark."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SEEDS = (121, 122, 123, 124)
MODES = (
    "static_aggressive",
    "oracle_boundary",
    "binary_recovery",
    "canary_recovery",
)
T_95_DF3 = 3.182446305284263
NUMERIC_METRICS = (
    "goodput_rps",
    "slo_compliant",
    "http_429",
    "http_503",
    "completed_but_late",
    "restart_count",
    "transition_duration_s",
    "tail_violation_area_s",
    "balanced_before_goodput_rps",
    "mixed_shift_goodput_rps",
    "balanced_return_goodput_rps",
)
TRANSITION_METRICS = (
    "mixed_transition_delay_s",
    "first_balanced_recovery_delay_s",
    "full_capacity_recovery_delay_s",
)


def summarize(values: Iterable[float], paired: bool = False) -> dict[str, float]:
    values = list(values)
    if len(values) < 2:
        raise ValueError("at least two values are required")
    output = {
        "mean": mean(values),
        "sample_stdev": stdev(values),
        "min": min(values),
        "max": max(values),
    }
    if paired:
        if len(values) != len(SEEDS):
            raise ValueError("paired interval requires four preregistered seeds")
        half = T_95_DF3 * output["sample_stdev"] / len(values) ** 0.5
        output.update({
            "n": len(values),
            "ci95_low": output["mean"] - half,
            "ci95_high": output["mean"] + half,
        })
    return output


def summarize_available(values: Iterable[float]) -> dict[str, Any]:
    """Describe an endpoint without hiding seeds where it was not reached."""
    values = list(values)
    if not values:
        return {
            "n": 0, "mean": None, "sample_stdev": None,
            "min": None, "max": None,
        }
    if len(values) == 1:
        return {
            "n": 1, "mean": values[0], "sample_stdev": None,
            "min": values[0], "max": values[0],
        }
    return {"n": len(values), **summarize(values)}


def transition_delay(result: dict[str, Any], boundary_s: float,
                     target_prefix: str, full: bool = False) -> float | None:
    matches = []
    for item in result["executions"]:
        if item["status"] != "applied" or item["started_offset_s"] < boundary_s:
            continue
        if not item["target_policy"].startswith(target_prefix):
            continue
        if full and ":canary-" in item["target_policy"]:
            continue
        matches.append(item["completed_offset_s"] - boundary_s)
    return min(matches) if matches else None


def validate_order(orders: list[list[str]]) -> None:
    expected = set(MODES)
    if len(orders) != len(MODES):
        raise ValueError("one cyclic order is required per mode")
    for order in orders:
        if len(order) != len(MODES) or set(order) != expected:
            raise ValueError(f"invalid mode order: {order}")
    for position in range(len(MODES)):
        if {order[position] for order in orders} != expected:
            raise ValueError(f"execution position {position + 1} is not balanced")


def validate_result(manifest: dict, result: dict, path: Path) -> None:
    expected = {
        item["request_id"]: (
            item["payload_sha256"], item["scheduled_offset_s"], item["phase"]
        )
        for item in manifest["trace"]
    }
    actual = {
        item["request_id"]: (
            item["payload_sha256"], item["scheduled_offset_s"], item["phase"]
        )
        for item in result.get("requests", [])
    }
    if (
        result.get("status") != "complete"
        or result.get("run_key") != manifest["run_key"]
        or result.get("control_errors")
        or actual != expected
    ):
        raise RuntimeError(f"invalid final evidence: {path}")


def row(seed: int, manifest: dict, result: dict) -> dict[str, Any]:
    summary = result["summary"]
    statuses = summary["status_counts"]
    return {
        "seed": seed,
        "mode": result["mode"]["name"],
        "trace_sha256": manifest["trace_sha256"],
        "attempted": summary["attempted"],
        "goodput_rps": summary["request_goodput"],
        "slo_compliant": summary["slo_compliant"],
        "http_429": statuses.get("429", 0),
        "http_503": statuses.get("503", 0),
        "completed_but_late": summary["completed"] - summary["slo_compliant"],
        "restart_count": result["restart_count"],
        "transition_duration_s": result["transition_duration_s"],
        "tail_violation_area_s": result["tail_violation_area_s"],
        "class_windows_without_success": result["class_windows_without_success"],
        "balanced_before_goodput_rps": result["by_phase"]["balanced_before"]["request_goodput"],
        "mixed_shift_goodput_rps": result["by_phase"]["mixed_shift"]["request_goodput"],
        "balanced_return_goodput_rps": result["by_phase"]["balanced_return"]["request_goodput"],
        "mixed_transition_delay_s": transition_delay(result, 60, "mixed_80_20:"),
        "first_balanced_recovery_delay_s": transition_delay(result, 210, "balanced:"),
        "full_capacity_recovery_delay_s": transition_delay(result, 210, "balanced:", True),
    }


def load_rows() -> tuple[list[dict[str, Any]], list[list[str]], list[dict]]:
    rows, orders, metadata = [], [], []
    model_identity = None
    for seed in SEEDS:
        directory = ROOT / "results" / f"generalization_7b_final_seed{seed}"
        manifest = json.loads((directory / "trace_manifest.json").read_text())
        identity = manifest["model"]
        if identity["served_model_name"] != "qwen2.5-7b":
            raise RuntimeError("unexpected served model alias")
        comparable_identity = {
            key: identity[key]
            for key in ("served_model_name", "identity_file_sha256", "weight_files", "weight_bytes")
        }
        if model_identity is None:
            model_identity = comparable_identity
        elif comparable_identity != model_identity:
            raise RuntimeError("model identity changed between final seeds")
        order = [item["name"] for item in manifest["config"]["modes"]]
        orders.append(order)
        metadata.append({
            "seed": seed,
            "trace_sha256": manifest["trace_sha256"],
            "attempted": len(manifest["trace"]),
            "order": order,
        })
        for mode in MODES:
            path = directory / mode / "result.json"
            result = json.loads(path.read_text())
            validate_result(manifest, result, path)
            rows.append(row(seed, manifest, result))
    validate_order(orders)
    return rows, orders, metadata


def paired(rows: list[dict[str, Any]], mode: str, reference: str) -> dict:
    lookup = {(item["seed"], item["mode"]): item for item in rows}
    output = {}
    for metric in NUMERIC_METRICS + TRANSITION_METRICS:
        differences = []
        missing_seeds = []
        for seed in SEEDS:
            value = lookup[(seed, mode)][metric]
            baseline = lookup[(seed, reference)][metric]
            if value is None or baseline is None:
                missing_seeds.append(seed)
            else:
                differences.append(value - baseline)
        if not missing_seeds:
            output[metric] = summarize(differences, paired=True)
        else:
            output[metric] = {
                **summarize_available(differences),
                "expected_pairs": len(SEEDS),
                "missing_seeds": missing_seeds,
                "ci95_low": None,
                "ci95_high": None,
                "inference_status": "incomplete_endpoint_no_preregistered_ci",
            }
    return output


def main() -> int:
    rows, orders, metadata = load_rows()
    aggregates = {
        mode: {
            metric: summarize(item[metric] for item in rows if item["mode"] == mode)
            for metric in NUMERIC_METRICS
        }
        for mode in MODES
    }
    for mode in MODES:
        for metric in TRANSITION_METRICS:
            values = [item[metric] for item in rows
                      if item["mode"] == mode and item[metric] is not None]
            aggregates[mode][metric] = {
                **summarize_available(values),
                "successes": len(values),
                "attempted_seeds": len(SEEDS),
                "success_rate": len(values) / len(SEEDS),
            }
    payload = {
        "schema_version": 1,
        "design": {
            "seeds": list(SEEDS), "modes": list(MODES), "orders": orders,
            "cyclic_position_balance_verified": True,
            "calibration_seeds_disjoint": True,
            "phase_boundaries_s": [0, 60, 210, 330],
        },
        "integrity": {
            "complete_results": len(rows),
            "expected_results": len(SEEDS) * len(MODES),
            "request_schedule_and_payload_identity_verified": True,
            "model_identity_stable": True,
            "control_error_count": 0,
            "paired_ci_method": "two-sided Student-t, df=3, four paired seeds",
        },
        "seed_metadata": metadata,
        "rows": rows,
        "aggregate_by_mode": aggregates,
        "paired_delta_canary_minus_binary": paired(rows, "canary_recovery", "binary_recovery"),
        "paired_delta_binary_minus_oracle": paired(rows, "binary_recovery", "oracle_boundary"),
        "paired_delta_canary_minus_oracle": paired(rows, "canary_recovery", "oracle_boundary"),
        "limitations": [
            "Four held-out seeds estimate dispersion but are not a production population.",
            "This tests model scale within Qwen2.5, not cross-architecture generalization.",
            "The oracle uses the same single-GPU executor and policy catalog.",
        ],
    }
    output = ROOT / "results/generalization_7b_final_analysis.json"
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    csv_path = ROOT / "results/generalization_7b_final_rows.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({mode: {
        "goodput_rps": aggregates[mode]["goodput_rps"]["mean"],
        "slo_compliant": aggregates[mode]["slo_compliant"]["mean"],
        "http_429": aggregates[mode]["http_429"]["mean"],
        "http_503": aggregates[mode]["http_503"]["mean"],
    } for mode in MODES}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
