#!/usr/bin/env python3
"""Derive and freeze the Qwen2.5-7B final benchmark from capacity evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FINAL_SEEDS = (121, 122, 123, 124)
MODE_ORDER = (
    "static_aggressive",
    "oracle_boundary",
    "binary_recovery",
    "canary_recovery",
)


def floor_half(value: float) -> float:
    return math.floor(value * 2) / 2


def derive_canary_limits(low: float, high: float) -> list[float]:
    if not all(math.isfinite(value) and value > 0 for value in (low, high)):
        raise ValueError("capacities must be finite and positive")
    limits = sorted(
        {
            floor_half(low + (high - low) / 3),
            floor_half(low + 2 * (high - low) / 3),
        }
    )
    limits = [value for value in limits if low < value < high]
    if len(limits) != 2:
        raise ValueError(
            f"capacity interval {low:g}->{high:g} cannot support two distinct "
            "0.5-rps canary stages"
        )
    return limits


def policy_candidate_name(name: str) -> str:
    if not (name.startswith("mbt") and name.endswith("_fcfs")):
        raise ValueError(f"unsupported capacity candidate: {name}")
    mbt = int(name.removeprefix("mbt").removesuffix("_fcfs"))
    return f"mbt{mbt}-seq256"


def build_artifacts(
    balanced_policy: dict[str, Any],
    mixed_policy: dict[str, Any],
    frozen_workload: dict[str, Any],
    base_controller: dict[str, Any],
) -> dict[str, Any]:
    if balanced_policy.get("status") != "ready" or mixed_policy.get("status") != "ready":
        raise ValueError("both 7B capacity policies must be ready")
    censored = {
        name
        for policy in (balanced_policy, mixed_policy)
        for name, status in policy.get("candidate_capacity_bound_status", {}).items()
        if status == "right_censored_lower_bound"
    }
    if censored:
        raise ValueError(
            "final benchmark cannot freeze while capacity is right-censored: "
            f"{sorted(censored)}"
        )

    balanced_capacities = {
        str(name): float(capacity)
        for name, capacity in balanced_policy["candidate_capacities"].items()
        if capacity is not None
    }
    mixed_selected = mixed_policy["selected"]
    mixed_candidate = str(mixed_selected["candidate"])
    low = float(mixed_selected["admission_limit_rps"])
    if mixed_candidate not in balanced_capacities:
        raise ValueError(
            "mixed server environment has no evidence-backed balanced capacity; "
            "compatible recovery cannot be evaluated"
        )
    high = balanced_capacities[mixed_candidate]
    if high <= low:
        raise ValueError("balanced compatible capacity must exceed mixed capacity")
    canary_limits = derive_canary_limits(low, high)

    balanced_selected = balanced_policy["selected"]
    selected_name = policy_candidate_name(str(balanced_selected["candidate"]))
    compatible = []
    for name, capacity in sorted(balanced_capacities.items()):
        candidate_name = policy_candidate_name(name)
        if candidate_name == selected_name:
            continue
        compatible.append(
            {
                "candidate": candidate_name,
                "robust_capacity_rps": capacity,
                "status": "ready",
            }
        )
    workload_policy = {
        "policies": [
            {
                "workload": "balanced",
                "selected_candidate": selected_name,
                "robust_capacity_rps": float(
                    balanced_selected["admission_limit_rps"]
                ),
                "status": "ready",
                "compatible_candidates": compatible,
            }
        ]
    }

    classes = {item["name"]: item for item in frozen_workload["classes"]}
    short = classes["interactive_short"]
    workload_profiles = {
        "description": "Experiment 017 frozen Qwen2.5-7B workload profile.",
        "profiles": [
            {
                "name": "balanced",
                "input_tokens": short["input_tokens"],
                "output_tokens": short["output_tokens"],
                "ttft_slo_ms": short["ttft_slo_ms"],
                "e2el_slo_ms": short["e2el_slo_ms"],
                "status": "completed",
            }
        ],
    }

    controller = dict(base_controller)
    controller["compatible_recovery_canary_admission_limits_rps"] = canary_limits
    controller["compatible_recovery_canary_pass_windows"] = 2

    balanced_rate = floor_half(2 * high / 3)
    mixed_rate = 2 * low
    if balanced_rate <= low:
        raise ValueError("derived balanced offered load does not exceed mixed capacity")

    primary_balanced = f"balanced:{selected_name}"
    primary_mixed = (
        f"mixed_80_20:selected:{mixed_selected['candidate']}"
    )
    catalog = {
        "static_aggressive": {
            "name": "static_aggressive",
            "adaptive": False,
            "initial_policy": primary_balanced,
        },
        "oracle_boundary": {
            "name": "oracle_boundary",
            "adaptive": False,
            "initial_policy": primary_balanced,
            "oracle_transitions": [
                {"at_s": 60, "profile": "mixed_80_20"},
                {"at_s": 210, "profile": "balanced"},
            ],
        },
        "binary_recovery": {
            "name": "binary_recovery",
            "adaptive": True,
            "initial_policy": primary_balanced,
            "controller_overrides": {
                "compatible_recovery_canary_admission_limits_rps": [],
                "compatible_recovery_canary_pass_windows": 2,
            },
        },
        "canary_recovery": {
            "name": "canary_recovery",
            "adaptive": True,
            "initial_policy": primary_balanced,
            "controller_overrides": {
                "compatible_recovery_canary_admission_limits_rps": canary_limits,
                "compatible_recovery_canary_pass_windows": 2,
            },
        },
    }
    configs = []
    for offset, seed in enumerate(FINAL_SEEDS):
        order = MODE_ORDER[offset:] + MODE_ORDER[:offset]
        configs.append(
            {
                "filename": f"generalization_7b_final_seed{seed}.json",
                "payload": {
                    "description": (
                        "Experiment 017 preregistered Qwen2.5-7B final model-scale "
                        "generalization benchmark with cyclic execution order."
                    ),
                    "seed": seed,
                    "metric_window_seconds": 30,
                    "derived_capacities": {
                        "mixed_safe_rps": low,
                        "balanced_compatible_rps": high,
                        "canary_limits_rps": canary_limits,
                    },
                    "phases": [
                        {
                            "name": "balanced_before",
                            "duration_s": 60,
                            "request_rate": balanced_rate,
                            "long_fraction": 0,
                        },
                        {
                            "name": "mixed_shift",
                            "duration_s": 150,
                            "request_rate": mixed_rate,
                            "long_fraction": 0.2,
                        },
                        {
                            "name": "balanced_return",
                            "duration_s": 120,
                            "request_rate": balanced_rate,
                            "long_fraction": 0,
                        },
                    ],
                    "modes": [catalog[name] for name in order],
                },
            }
        )
    return {
        "low_capacity_rps": low,
        "high_compatible_capacity_rps": high,
        "canary_limits_rps": canary_limits,
        "balanced_offered_rps": balanced_rate,
        "mixed_offered_rps": mixed_rate,
        "workload_policy": workload_policy,
        "workload_profiles": workload_profiles,
        "controller": controller,
        "configs": configs,
        "primary_mixed_policy": primary_mixed,
    }


def save_exact(path: Path, payload: Any) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"refusing to overwrite different final artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def main() -> int:
    artifacts = build_artifacts(
        json.loads((ROOT / "results/generalization_7b_balanced_capacity_final_policy.json").read_text()),
        json.loads((ROOT / "results/generalization_7b_mixed_capacity_final_policy.json").read_text()),
        json.loads((ROOT / "configs/generalization_7b_workload.json").read_text()),
        json.loads((ROOT / "configs/controller.json").read_text()),
    )
    save_exact(
        ROOT / "results/generalization_7b_workload_policy.json",
        artifacts["workload_policy"],
    )
    save_exact(
        ROOT / "configs/generalization_7b_workload_profiles.json",
        artifacts["workload_profiles"],
    )
    save_exact(
        ROOT / "configs/generalization_7b_controller.json",
        artifacts["controller"],
    )
    for item in artifacts["configs"]:
        save_exact(ROOT / "configs" / item["filename"], item["payload"])
    print(json.dumps({key: artifacts[key] for key in (
        "low_capacity_rps", "high_compatible_capacity_rps",
        "canary_limits_rps", "balanced_offered_rps", "mixed_offered_rps",
    )}, indent=2))
    print("EXPERIMENT017_FINAL_CONFIGS_FROZEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
