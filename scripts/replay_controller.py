#!/usr/bin/env python3
"""Deterministic end-to-end replay of controller switch and rollback logic."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

from slo_autotuner.controller import (
    AdaptiveServingController,
    ClassWindowMetrics,
    ControllerConfig,
    RequestObservation,
    RollingWorkloadDetector,
    load_policy_catalog,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def add_phase(
    controller: AdaptiveServingController,
    start_s: float,
    count: int,
    pattern: tuple[str, ...],
    shapes: dict[str, tuple[int, int]],
) -> None:
    for index in range(count):
        shape = pattern[index % len(pattern)]
        input_tokens, output_tokens = shapes[shape]
        controller.observe_request(
            RequestObservation(
                timestamp_s=start_s + index,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "controller.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "controller-demo.json",
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new path to preserve existing evidence")

    config = ControllerConfig.from_json(args.config)
    catalog = load_policy_catalog(
        PROJECT_ROOT / "results" / "workload_policy.json",
        PROJECT_ROOT / "configs" / "workload_profiles.json",
        PROJECT_ROOT / "results" / "mixed_policy.json",
        config.mixed_profile_name,
        config.default_max_num_seqs,
    )
    detector = RollingWorkloadDetector(
        config.rolling_window_seconds,
        config.minimum_samples,
        config.shape_prototypes,
        config.profile_distributions,
    )
    controller = AdaptiveServingController(config, catalog, detector)
    shapes = {
        item.name: (item.input_tokens, item.output_tokens)
        for item in config.shape_prototypes
    }
    decisions = []

    add_phase(controller, 0, 60, ("balanced",), shapes)
    decisions.append(controller.tick(60).to_dict())

    add_phase(
        controller,
        61,
        60,
        ("balanced", "balanced", "balanced", "balanced", "prefill_heavy"),
        shapes,
    )
    for timestamp in (121, 131, 141):
        decisions.append(controller.tick(timestamp).to_dict())

    passing = {
        "interactive_short": ClassWindowMetrics(40, 0, 70, 370),
        "document_long": ClassWindowMetrics(10, 0, 150, 450),
    }
    violating = {
        "interactive_short": ClassWindowMetrics(40, 0, 90, 430, violating_request_ids=(1,)),
        "document_long": ClassWindowMetrics(10, 0, 160, 460),
    }
    decisions.append(controller.report_slo_window(145, passing).to_dict())
    decisions.append(controller.report_slo_window(150, violating).to_dict())
    # An overlapping window with the same slow request must not confirm rollback.
    decisions.append(controller.report_slo_window(155, violating).to_dict())
    fresh_violation = dict(violating)
    fresh_violation["interactive_short"] = replace(
        violating["interactive_short"], violating_request_ids=(2,)
    )
    decisions.append(controller.report_slo_window(160, fresh_violation).to_dict())

    add_phase(controller, 400, 60, ("balanced",), shapes)
    for timestamp in (460, 470, 480):
        decisions.append(controller.tick(timestamp).to_dict())

    transitions = [
        decision["action"]
        for decision in decisions
        if decision["action"] in {"switch", "rollback"}
    ]
    expected = ["switch", "rollback", "switch"]
    if transitions != expected:
        raise RuntimeError(f"unexpected transition sequence: {transitions}")

    payload = {
        "schema_version": 1,
        "scenario": (
            "balanced -> mixed_80_20 -> two SLO violations -> rollback -> "
            "balanced after cooldown"
        ),
        "decisions": decisions,
        "transition_sequence": transitions,
        "final_state": controller.state_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)

    for decision in decisions:
        print(
            f"t={decision['timestamp_s']:g} action={decision['action']} "
            f"policy={decision['to_policy']} reason={decision['reason']}"
        )
    print(f"transition_sequence={transitions}")
    print(f"wrote={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
