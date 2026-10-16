#!/usr/bin/env python3
"""Validate and summarize paired binary-versus-canary GPU experiments."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
MODES = ("binary_recovery", "canary_recovery")


def load_seed(seed: int) -> dict:
    directory = ROOT / "results" / f"canary_tradeoff_seed{seed}"
    manifest = json.loads((directory / "trace_manifest.json").read_text())
    expected = {
        item["request_id"]: (
            item["payload_sha256"],
            item["scheduled_offset_s"],
            item["phase"],
        )
        for item in manifest["trace"]
    }
    output = {
        "seed": seed,
        "trace_sha256": manifest["trace_sha256"],
        "order": [item["name"] for item in manifest["config"]["modes"]],
        "modes": {},
    }
    return_start = next(
        phase["start_s"]
        for phase in manifest["phases"]
        if phase["name"] == "balanced_return"
    )
    for mode_name in MODES:
        result = json.loads((directory / mode_name / "result.json").read_text())
        actual = {
            item["request_id"]: (
                item["payload_sha256"],
                item["scheduled_offset_s"],
                item["phase"],
            )
            for item in result["requests"]
        }
        if (
            result["status"] != "complete"
            or result["run_key"] != manifest["run_key"]
            or actual != expected
            or len(result["requests"]) != len(expected)
            or result["control_errors"]
        ):
            raise RuntimeError(f"invalid evidence: seed={seed} mode={mode_name}")
        return_transitions = [
            item
            for item in result["executions"]
            if item["started_offset_s"] >= return_start
            and item["status"] == "applied"
            and item["target_policy"].startswith("balanced:")
        ]
        full = [
            item
            for item in return_transitions
            if ":canary-" not in item["target_policy"]
        ]
        phase = result["by_phase"]["balanced_return"]
        output["modes"][mode_name] = {
            "goodput_rps": result["summary"]["request_goodput"],
            "compliant": result["summary"]["slo_compliant"],
            "statuses": result["summary"]["status_counts"],
            "restart_count": result["restart_count"],
            "tail_violation_area_s": result["tail_violation_area_s"],
            "balanced_return": {
                "goodput_rps": phase["request_goodput"],
                "compliant": phase["slo_compliant"],
                "statuses": phase["status_counts"],
                "first_recovery_delay_s": min(
                    item["completed_offset_s"] - return_start
                    for item in return_transitions
                ),
                "full_capacity_delay_s": min(
                    item["completed_offset_s"] - return_start
                    for item in full
                ),
                "transitions": return_transitions,
            },
        }
    binary = output["modes"]["binary_recovery"]
    canary = output["modes"]["canary_recovery"]
    output["delta_canary_minus_binary"] = {
        "goodput_rps": canary["goodput_rps"] - binary["goodput_rps"],
        "compliant": canary["compliant"] - binary["compliant"],
        "http_429": canary["statuses"].get("429", 0)
        - binary["statuses"].get("429", 0),
        "http_503": canary["statuses"].get("503", 0)
        - binary["statuses"].get("503", 0),
        "restart_count": canary["restart_count"] - binary["restart_count"],
        "return_goodput_rps": canary["balanced_return"]["goodput_rps"]
        - binary["balanced_return"]["goodput_rps"],
        "first_recovery_delay_s": canary["balanced_return"][
            "first_recovery_delay_s"
        ]
        - binary["balanced_return"]["first_recovery_delay_s"],
        "full_capacity_delay_s": canary["balanced_return"][
            "full_capacity_delay_s"
        ]
        - binary["balanced_return"]["full_capacity_delay_s"],
    }
    return output


def main() -> int:
    seeds = [load_seed(seed) for seed in (86, 87)]
    delta_keys = seeds[0]["delta_canary_minus_binary"]
    aggregate = {
        key: {
            "mean": mean(seed["delta_canary_minus_binary"][key] for seed in seeds),
            "values": [seed["delta_canary_minus_binary"][key] for seed in seeds],
        }
        for key in delta_keys
    }
    payload = {
        "schema_version": 1,
        "seeds": seeds,
        "aggregate_delta_canary_minus_binary": aggregate,
        "fault_injection": json.loads(
            (ROOT / "results" / "live_canary_scenarios.json").read_text()
        )["slow_request_exposure_reduction"],
        "limitations": [
            "Two paired seeds with alternating order are a trade-off pilot, not a population estimate.",
            "The slow-backend exposure result is controlled fault injection, not a GPU failure probability.",
            "Full-capacity delay includes SLO evidence collection and admission-only transaction time.",
        ],
    }
    output = ROOT / "results" / "canary_tradeoff_analysis.json"
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: value["mean"]
                for key, value in aggregate.items()
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
