#!/usr/bin/env python3
"""Deterministic scenarios that force each controller safety branch to matter."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from slo_autotuner.controller import (  # noqa: E402
    AdaptiveServingController,
    ClassWindowMetrics,
    ControllerConfig,
    DetectorSnapshot,
    load_policy_catalog,
)


class ScriptedDetector:
    def __init__(self, snapshots: Iterable[DetectorSnapshot]) -> None:
        self.snapshots = iter(snapshots)

    def snapshot(self, now_s: float) -> DetectorSnapshot:
        snapshot = next(self.snapshots)
        return replace(snapshot, timestamp_s=now_s)


def snapshot(
    best_profile: str,
    *,
    best_distance: float = 0.0,
    active_profile: str,
    active_distance: float = 1.0,
) -> DetectorSnapshot:
    distances = {
        "balanced": 1.0,
        "mixed_80_20": 1.0,
        "prefill_heavy_4x": 1.0,
        "decode_heavy_4x": 1.0,
        best_profile: best_distance,
        active_profile: active_distance,
    }
    return DetectorSnapshot(
        timestamp_s=0,
        sample_count=100,
        estimated_rps=10,
        distribution={},
        profile_distances=distances,
        best_profile=best_profile,
        best_distance=best_distance,
        status="ready",
    )


def catalog_for(config: ControllerConfig):
    return load_policy_catalog(
        PROJECT_ROOT / "results" / "workload_policy.json",
        PROJECT_ROOT / "configs" / "workload_profiles.json",
        PROJECT_ROOT / "results" / "mixed_policy.json",
        config.mixed_profile_name,
        config.default_max_num_seqs,
    )


def controller_with(
    config: ControllerConfig,
    snapshots: Iterable[DetectorSnapshot],
) -> AdaptiveServingController:
    return AdaptiveServingController(config, catalog_for(config), ScriptedDetector(snapshots))


def decision_summary(decisions) -> dict:
    transitions = [
        decision.to_dict()
        for decision in decisions
        if decision.action in {"switch", "rollback"}
    ]
    return {
        "actions": [decision.action for decision in decisions],
        "transitions": transitions,
        "restart_count": sum(item["requires_server_restart"] for item in transitions),
        "final_policy": decisions[-1].to_policy,
    }


def run_scenarios(config: ControllerConfig, restart_cost_s: float) -> dict:
    strong_mixed = snapshot("mixed_80_20", active_profile="balanced")
    strong_balanced = snapshot("balanced", active_profile="mixed_80_20")

    full = controller_with(config, [strong_mixed, strong_balanced])
    no_confirmation_config = replace(config, switch_confirmation_windows=1)
    no_confirmation = controller_with(
        no_confirmation_config, [strong_mixed, strong_balanced]
    )
    confirmation_full = [full.tick(10), full.tick(20)]
    confirmation_ablated = [
        no_confirmation.tick(10),
        no_confirmation.tick(20),
    ]

    weak_mixed = snapshot(
        "mixed_80_20",
        best_distance=0.09,
        active_profile="balanced",
        active_distance=0.10,
    )
    full = controller_with(config, [weak_mixed] * 3)
    no_hysteresis_config = replace(
        config, switch_margin=0.0, max_profile_distance=1.0
    )
    no_hysteresis = controller_with(no_hysteresis_config, [weak_mixed] * 3)
    hysteresis_full = [full.tick(now) for now in (10, 20, 30)]
    hysteresis_ablated = [no_hysteresis.tick(now) for now in (10, 20, 30)]

    strong_decode = snapshot("decode_heavy_4x", active_profile="mixed_80_20")
    back_to_mixed = snapshot("mixed_80_20", active_profile="decode_heavy_4x")
    cooldown_base = replace(config, switch_confirmation_windows=1)
    cooldown_full = controller_with(
        cooldown_base, [strong_mixed, strong_decode, strong_decode, back_to_mixed]
    )
    cooldown_disabled = controller_with(
        replace(cooldown_base, cooldown_seconds=0.0),
        [strong_mixed, strong_decode, strong_decode, back_to_mixed],
    )
    cooldown_full_decisions = [cooldown_full.tick(now) for now in (10, 20, 30, 40)]
    cooldown_disabled_decisions = [
        cooldown_disabled.tick(now) for now in (10, 20, 30, 40)
    ]

    full = controller_with(config, [])
    rollback_disabled = controller_with(
        replace(config, rollback_confirmation_windows=1_000_000), []
    )
    for controller in (full, rollback_disabled):
        controller.force_active_policy(
            controller.catalog.primary_for("mixed_80_20").name, 0, 0
        )
    violating_1 = {
        "interactive_short": ClassWindowMetrics(40, 0, 90, 430, (1001,)),
        "document_long": ClassWindowMetrics(10, 0, 150, 450),
    }
    violating_2 = {
        "interactive_short": ClassWindowMetrics(40, 0, 90, 430, (1001, 1002)),
        "document_long": ClassWindowMetrics(10, 0, 150, 450),
    }
    rollback_full = [
        full.report_slo_window(10, violating_1),
        full.report_slo_window(20, violating_2),
    ]
    rollback_ablated = [
        rollback_disabled.report_slo_window(10, violating_1),
        rollback_disabled.report_slo_window(20, violating_2),
    ]

    weak_balanced = snapshot(
        "balanced",
        best_distance=0.09,
        active_profile="mixed_80_20",
        active_distance=0.10,
    )
    asymmetric = controller_with(config, [weak_balanced])
    legacy = controller_with(
        replace(
            config,
            compatible_recovery_confirmation_windows=config.switch_confirmation_windows,
            compatible_recovery_switch_margin=config.switch_margin,
        ),
        [weak_balanced],
    )
    for controller in (asymmetric, legacy):
        controller.force_active_policy(
            controller.catalog.primary_for("mixed_80_20").name, 0, 300
        )
    asymmetric_decision = asymmetric.tick(10)
    legacy_decision = legacy.tick(10)

    scenarios = {
        "transient_false_positive": {
            "full": decision_summary(confirmation_full),
            "without_confirmation": decision_summary(confirmation_ablated),
            "interpretation": "confirmation avoids a restart on a one-window false signal",
        },
        "weak_distance_advantage": {
            "full": decision_summary(hysteresis_full),
            "without_distance_hysteresis": decision_summary(hysteresis_ablated),
            "interpretation": "distance margin avoids switching on a persistent but tiny advantage",
        },
        "rapid_incompatible_reversal": {
            "full": decision_summary(cooldown_full_decisions),
            "without_cooldown": decision_summary(cooldown_disabled_decisions),
            "interpretation": "cooldown blocks repeated model-reload transitions",
        },
        "persistent_fresh_slo_violations": {
            "full": decision_summary(rollback_full),
            "without_rollback": decision_summary(rollback_ablated),
            "interpretation": "without rollback, the controller leaves a persistently violating primary after two fresh windows",
        },
        "compatible_high_capacity_recovery": {
            "asymmetric": decision_summary([asymmetric_decision]),
            "legacy_symmetric": decision_summary([legacy_decision]),
            "interpretation": "asymmetric recovery changes admission without a model restart",
        },
    }
    for scenario in scenarios.values():
        for value in scenario.values():
            if isinstance(value, dict) and "restart_count" in value:
                value["restart_downtime_proxy_s"] = (
                    value["restart_count"] * restart_cost_s
                )

    expected = {
        "transient_false_positive": (0, 1),
        "weak_distance_advantage": (0, 1),
        "rapid_incompatible_reversal": (1, 3),
        "persistent_fresh_slo_violations": (1, 0),
        "compatible_high_capacity_recovery": (0, 0),
    }
    observed = {
        "transient_false_positive": (
            scenarios["transient_false_positive"]["full"]["restart_count"],
            scenarios["transient_false_positive"]["without_confirmation"]["restart_count"],
        ),
        "weak_distance_advantage": (
            scenarios["weak_distance_advantage"]["full"]["restart_count"],
            scenarios["weak_distance_advantage"]["without_distance_hysteresis"]["restart_count"],
        ),
        "rapid_incompatible_reversal": (
            scenarios["rapid_incompatible_reversal"]["full"]["restart_count"],
            scenarios["rapid_incompatible_reversal"]["without_cooldown"]["restart_count"],
        ),
        "persistent_fresh_slo_violations": (
            scenarios["persistent_fresh_slo_violations"]["full"]["restart_count"],
            scenarios["persistent_fresh_slo_violations"]["without_rollback"]["restart_count"],
        ),
        "compatible_high_capacity_recovery": (
            scenarios["compatible_high_capacity_recovery"]["asymmetric"]["restart_count"],
            scenarios["compatible_high_capacity_recovery"]["legacy_symmetric"]["restart_count"],
        ),
    }
    if observed != expected:
        raise RuntimeError(f"scenario expectations failed: {observed} != {expected}")
    return {
        "schema_version": 1,
        "measured_restart_cost_s": restart_cost_s,
        "scenarios": scenarios,
        "expected_restart_pairs": expected,
    }


def load_restart_cost() -> float:
    path = (
        PROJECT_ROOT
        / "results"
        / "oracle_ablation_seed81"
        / "oracle_boundary"
        / "result.json"
    )
    if not path.exists():
        return 45.17
    result = json.loads(path.read_text(encoding="utf-8"))
    return sum(
        item["duration_s"]
        for item in result["executions"]
        if item["requires_server_restart"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "controller_safety_scenarios.json",
    )
    args = parser.parse_args()
    config = ControllerConfig.from_json(PROJECT_ROOT / "configs" / "controller.json")
    payload = run_scenarios(config, load_restart_cost())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
