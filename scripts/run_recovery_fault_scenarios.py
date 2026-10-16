#!/usr/bin/env python3
"""Counterfactual test for SLO rollback after compatible capacity recovery."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from slo_autotuner.controller import (  # noqa: E402
    AdaptiveServingController,
    ClassWindowMetrics,
    ControllerConfig,
    DetectorSnapshot,
    load_policy_catalog,
)


class BalancedDetector:
    def snapshot(self, now_s: float) -> DetectorSnapshot:
        return DetectorSnapshot(
            timestamp_s=now_s,
            sample_count=100,
            estimated_rps=24,
            distribution={
                "balanced": 1.0,
                "prefill_heavy": 0.0,
                "decode_heavy": 0.0,
            },
            profile_distances={
                "balanced": 0.0,
                "mixed_80_20": 0.2,
                "prefill_heavy_4x": 1.0,
                "decode_heavy_4x": 1.0,
            },
            best_profile="balanced",
            best_distance=0.0,
            status="ready",
        )


def build_controller(enabled: bool) -> AdaptiveServingController:
    config = ControllerConfig.from_json(PROJECT_ROOT / "configs" / "controller.json")
    config = replace(
        config,
        compatible_recovery_rollback_enabled=enabled,
        compatible_recovery_canary_admission_limits_rps=(),
    )
    catalog = load_policy_catalog(
        PROJECT_ROOT / "results" / "workload_policy.json",
        PROJECT_ROOT / "configs" / "workload_profiles.json",
        PROJECT_ROOT / "results" / "mixed_policy.json",
        config.mixed_profile_name,
        config.default_max_num_seqs,
    )
    controller = AdaptiveServingController(config, catalog, BalancedDetector())
    mixed = catalog.primary_for(config.mixed_profile_name)
    controller.force_active_policy(mixed.name, 0, 0)
    return controller


def run_mode(enabled: bool) -> dict:
    controller = build_controller(enabled)
    decisions = [controller.tick(10)]
    decisions.append(
        controller.report_slo_window(
            20,
            {"balanced": ClassWindowMetrics(40, 0, 120, 430, (5001,))},
        )
    )
    decisions.append(
        controller.report_slo_window(
            30,
            {"balanced": ClassWindowMetrics(40, 0, 125, 440, (5001, 5002))},
        )
    )
    decisions.append(controller.tick(40))
    transitions = [
        decision.to_dict()
        for decision in decisions
        if decision.action in {"switch", "rollback"}
    ]
    return {
        "enabled": enabled,
        "actions": [decision.action for decision in decisions],
        "reasons": [decision.reason for decision in decisions],
        "transitions": transitions,
        "restart_count": sum(
            decision.requires_server_restart
            for decision in decisions
            if decision.action in {"switch", "rollback"}
        ),
        "final_state": controller.state_dict(),
    }


def main() -> int:
    enabled = run_mode(True)
    disabled = run_mode(False)
    if enabled["actions"] != ["switch", "hold", "rollback", "hold"]:
        raise RuntimeError(f"enabled scenario failed: {enabled['actions']}")
    if disabled["actions"] != ["switch", "hold", "alert", "hold"]:
        raise RuntimeError(f"disabled scenario failed: {disabled['actions']}")
    if enabled["restart_count"] != 0 or disabled["restart_count"] != 0:
        raise RuntimeError("compatible recovery scenario must not restart the model")
    if enabled["final_state"]["admission_limit_rps"] != 3:
        raise RuntimeError("enabled guard did not restore conservative admission")
    if disabled["final_state"]["admission_limit_rps"] != 24:
        raise RuntimeError("disabled counterfactual unexpectedly reduced admission")
    payload = {
        "schema_version": 1,
        "question": (
            "Can fresh SLO violations after compatible capacity recovery restore "
            "the last safe policy without restarting or immediately retrying?"
        ),
        "guard_enabled": enabled,
        "guard_disabled": disabled,
        "interpretation": (
            "The enabled guard performs an admission-only rollback from 24 to 3 "
            "req/s and blocks immediate re-expansion; the disabled counterfactual "
            "can only alert and remains at 24 req/s."
        ),
    }
    output = PROJECT_ROOT / "results" / "recovery_fault_scenarios.json"
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
