#!/usr/bin/env python3
"""Validate and aggregate the Experiment 015 final benchmark."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SEEDS = tuple(range(88, 93))
MODES = (
    "static_aggressive",
    "binary_recovery",
    "canary_recovery",
    "oracle_boundary",
    "static_conservative",
)
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

# Two-sided 95% Student-t critical value for the preregistered five paired seeds
# (four degrees of freedom). Keeping this constant explicit avoids a scipy
# dependency and prevents silently applying a large-sample normal interval.
PAIRED_T_95_DF4 = 2.7764451051977987


def summarize_values(values: Iterable[float]) -> dict[str, float]:
    materialized = list(values)
    if len(materialized) < 2:
        raise ValueError("at least two values are required")
    return {
        "mean": mean(materialized),
        "sample_stdev": stdev(materialized),
        "min": min(materialized),
        "max": max(materialized),
    }


def summarize_paired_values(values: Iterable[float]) -> dict[str, float]:
    materialized = list(values)
    if len(materialized) != len(SEEDS):
        raise ValueError(
            f"paired interval requires {len(SEEDS)} preregistered seeds"
        )
    summary = summarize_values(materialized)
    half_width = (
        PAIRED_T_95_DF4
        * summary["sample_stdev"]
        / len(materialized) ** 0.5
    )
    summary.update(
        {
            "n": len(materialized),
            "ci95_low": summary["mean"] - half_width,
            "ci95_high": summary["mean"] + half_width,
        }
    )
    return summary


def validate_cyclic_orders(orders: list[list[str]]) -> None:
    if len(orders) != len(MODES):
        raise ValueError("one cyclic order is required per mode")
    expected = set(MODES)
    for order in orders:
        if len(order) != len(MODES) or set(order) != expected:
            raise ValueError(f"invalid mode order: {order}")
    for position in range(len(MODES)):
        if {order[position] for order in orders} != expected:
            raise ValueError(f"execution position {position + 1} is not balanced")


def transition_delay(
    result: dict[str, Any],
    boundary_s: float,
    target_prefix: str,
    require_full_capacity: bool = False,
) -> float | None:
    matches = []
    for item in result["executions"]:
        if item["status"] != "applied" or item["started_offset_s"] < boundary_s:
            continue
        target = item["target_policy"]
        if not target.startswith(target_prefix):
            continue
        if require_full_capacity and ":canary-" in target:
            continue
        matches.append(item["completed_offset_s"] - boundary_s)
    return min(matches) if matches else None


def validate_requests(manifest: dict, result: dict, path: Path) -> None:
    expected = {
        item["request_id"]: (
            item["payload_sha256"],
            item["scheduled_offset_s"],
            item["phase"],
        )
        for item in manifest["trace"]
    }
    actual = {
        item["request_id"]: (
            item["payload_sha256"],
            item["scheduled_offset_s"],
            item["phase"],
        )
        for item in result.get("requests", [])
    }
    if (
        result.get("status") != "complete"
        or result.get("run_key") != manifest["run_key"]
        or result.get("control_errors")
        or actual != expected
    ):
        raise RuntimeError(f"invalid benchmark evidence: {path}")


def row_for(seed: int, manifest: dict, result: dict) -> dict[str, Any]:
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
        "balanced_before_goodput_rps": result["by_phase"]["balanced_before"][
            "request_goodput"
        ],
        "mixed_shift_goodput_rps": result["by_phase"]["mixed_shift"][
            "request_goodput"
        ],
        "balanced_return_goodput_rps": result["by_phase"]["balanced_return"][
            "request_goodput"
        ],
        "mixed_transition_delay_s": transition_delay(
            result, 60.0, "mixed_80_20:"
        ),
        "first_balanced_recovery_delay_s": transition_delay(
            result, 210.0, "balanced:"
        ),
        "full_capacity_recovery_delay_s": transition_delay(
            result, 210.0, "balanced:", require_full_capacity=True
        ),
    }


def load_rows() -> tuple[list[dict[str, Any]], list[list[str]], list[dict]]:
    rows: list[dict[str, Any]] = []
    orders: list[list[str]] = []
    seed_metadata = []
    for seed in SEEDS:
        directory = ROOT / "results" / f"final_benchmark_seed{seed}"
        manifest = json.loads(
            (directory / "trace_manifest.json").read_text(encoding="utf-8")
        )
        order = [mode["name"] for mode in manifest["config"]["modes"]]
        orders.append(order)
        seed_metadata.append(
            {
                "seed": seed,
                "trace_sha256": manifest["trace_sha256"],
                "attempted": len(manifest["trace"]),
                "order": order,
            }
        )
        if set(order) != set(MODES):
            raise RuntimeError(f"seed {seed} does not contain the final mode set")
        for mode in MODES:
            path = directory / mode / "result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            validate_requests(manifest, result, path)
            rows.append(row_for(seed, manifest, result))
    validate_cyclic_orders(orders)
    return rows, orders, seed_metadata


def paired_deltas(
    rows: list[dict[str, Any]], mode: str, reference: str
) -> dict[str, dict[str, float]]:
    by_key = {(row["seed"], row["mode"]): row for row in rows}
    output = {}
    for metric in NUMERIC_METRICS + TRANSITION_METRICS:
        values = [
            by_key[(seed, mode)][metric] - by_key[(seed, reference)][metric]
            for seed in SEEDS
        ]
        output[metric] = summarize_paired_values(values)
    return output


def main() -> int:
    rows, orders, seed_metadata = load_rows()
    aggregates = {
        mode: {
            metric: summarize_values(
                row[metric] for row in rows if row["mode"] == mode
            )
            for metric in NUMERIC_METRICS
        }
        for mode in MODES
    }
    for mode in MODES:
        for metric in TRANSITION_METRICS:
            values = [
                row[metric]
                for row in rows
                if row["mode"] == mode and row[metric] is not None
            ]
            if values:
                aggregates[mode][metric] = summarize_values(values)
    payload = {
        "schema_version": 2,
        "design": {
            "seeds": list(SEEDS),
            "modes": list(MODES),
            "orders": orders,
            "cyclic_position_balance_verified": True,
            "phase_boundaries_s": [0, 60, 210, 330],
        },
        "integrity": {
            "complete_results": len(rows),
            "expected_results": len(SEEDS) * len(MODES),
            "request_schedule_and_payload_identity_verified": True,
            "run_key_identity_verified": True,
            "control_error_count": 0,
            "cyclic_position_balance_verified": True,
            "paired_ci_method": "two-sided Student-t, df=4, five paired seeds",
        },
        "seed_metadata": seed_metadata,
        "rows": rows,
        "aggregate_by_mode": aggregates,
        "paired_delta_canary_minus_binary": paired_deltas(
            rows, "canary_recovery", "binary_recovery"
        ),
        "paired_delta_canary_minus_oracle": paired_deltas(
            rows, "canary_recovery", "oracle_boundary"
        ),
        "paired_delta_binary_minus_oracle": paired_deltas(
            rows, "binary_recovery", "oracle_boundary"
        ),
        "fault_injection_context": json.loads(
            (ROOT / "results" / "live_canary_scenarios.json").read_text(
                encoding="utf-8"
            )
        )["slow_request_exposure_reduction"],
        "limitations": [
            "Five seeds estimate run-to-run dispersion but are not a production population.",
            "Cyclic order balances serial execution position; it cannot eliminate all temporal drift.",
            "The phase-boundary oracle is constrained by the same policy catalog and single-GPU executor.",
            "Fault-radius evidence remains controlled HTTP/SSE fault injection and is reported separately.",
        ],
    }
    output = ROOT / "results" / "final_benchmark_analysis.json"
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    csv_path = ROOT / "results" / "final_benchmark_rows.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(
        json.dumps(
            {
                mode: {
                    "goodput_rps": aggregates[mode]["goodput_rps"]["mean"],
                    "slo_compliant": aggregates[mode]["slo_compliant"]["mean"],
                    "http_429": aggregates[mode]["http_429"]["mean"],
                    "http_503": aggregates[mode]["http_503"]["mean"],
                }
                for mode in MODES
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
