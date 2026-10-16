#!/usr/bin/env python3
"""Create alternating-order paired configs for the canary trade-off study."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def mode(name: str, canary_limits: list[int]) -> dict:
    return {
        "name": name,
        "adaptive": True,
        "initial_policy": "balanced:mbt2048-seq256",
        "controller_overrides": {
            "compatible_recovery_canary_admission_limits_rps": canary_limits,
            "compatible_recovery_canary_pass_windows": 2,
        },
    }


def config(seed: int, order: list[str]) -> dict:
    modes = {
        "binary_recovery": mode("binary_recovery", []),
        "canary_recovery": mode("canary_recovery", [8, 16]),
    }
    return {
        "description": (
            "Paired real-GPU cost of 3->8->16->24 canary recovery versus "
            "binary 3->24 recovery, with alternating execution order."
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
        "modes": [modes[name] for name in order],
    }


def save_exact(path: Path, payload: dict) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"refusing to overwrite different config: {path}")
    path.write_text(rendered, encoding="utf-8")


def main() -> int:
    configs = {
        "canary_tradeoff_seed86.json": config(
            86, ["binary_recovery", "canary_recovery"]
        ),
        "canary_tradeoff_seed87.json": config(
            87, ["canary_recovery", "binary_recovery"]
        ),
    }
    for name, payload in configs.items():
        path = ROOT / "configs" / name
        save_exact(path, payload)
        print(f"{name} {sum(p['duration_s'] for p in payload['phases']):g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
