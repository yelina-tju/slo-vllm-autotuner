#!/usr/bin/env python3
"""Create the balanced-order final benchmark configs for Experiment 015."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEEDS = tuple(range(88, 93))
MODE_ORDER = (
    "static_aggressive",
    "binary_recovery",
    "canary_recovery",
    "oracle_boundary",
    "static_conservative",
)


def modes() -> dict[str, dict]:
    return {
        "static_aggressive": {
            "name": "static_aggressive",
            "adaptive": False,
            "initial_policy": "balanced:mbt2048-seq256",
        },
        "binary_recovery": {
            "name": "binary_recovery",
            "adaptive": True,
            "initial_policy": "balanced:mbt2048-seq256",
            "controller_overrides": {
                "compatible_recovery_canary_admission_limits_rps": [],
                "compatible_recovery_canary_pass_windows": 2,
            },
        },
        "canary_recovery": {
            "name": "canary_recovery",
            "adaptive": True,
            "initial_policy": "balanced:mbt2048-seq256",
            "controller_overrides": {
                "compatible_recovery_canary_admission_limits_rps": [8, 16],
                "compatible_recovery_canary_pass_windows": 2,
            },
        },
        "oracle_boundary": {
            "name": "oracle_boundary",
            "adaptive": False,
            "initial_policy": "balanced:mbt2048-seq256",
            "oracle_transitions": [
                {"at_s": 60, "profile": "mixed_80_20"},
                {"at_s": 210, "profile": "balanced"},
            ],
        },
        "static_conservative": {
            "name": "static_conservative",
            "adaptive": False,
            "initial_policy": "mixed_80_20:selected:mbt1024_fcfs",
        },
    }


def rotated_order(offset: int) -> list[str]:
    return list(MODE_ORDER[offset:] + MODE_ORDER[:offset])


def config(seed: int, order: list[str]) -> dict:
    catalog = modes()
    return {
        "description": (
            "Experiment 015 final real-GPU benchmark: two static baselines, "
            "boundary oracle, binary recovery and canary recovery on an "
            "identical trace, with cyclic execution-order balance."
        ),
        "seed": seed,
        "metric_window_seconds": 30,
        "phases": [
            {
                "name": "balanced_before",
                "duration_s": 60,
                "request_rate": 16,
                "long_fraction": 0,
            },
            {
                "name": "mixed_shift",
                "duration_s": 150,
                "request_rate": 6,
                "long_fraction": 0.2,
            },
            {
                "name": "balanced_return",
                "duration_s": 120,
                "request_rate": 16,
                "long_fraction": 0,
            },
        ],
        "modes": [catalog[name] for name in order],
    }


def save_exact(path: Path, payload: dict) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"refusing to overwrite different config: {path}")
    path.write_text(rendered, encoding="utf-8")


def main() -> int:
    for offset, seed in enumerate(SEEDS):
        order = rotated_order(offset)
        payload = config(seed, order)
        path = ROOT / "configs" / f"final_benchmark_seed{seed}.json"
        save_exact(path, payload)
        print(f"{path.name}: {' -> '.join(order)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
