#!/usr/bin/env python3
"""Freeze a capacity-grid extension only for right-censored 7B candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_SEEDS = [114, 115, 116]
EXTENSION_RATES = {
    "balanced": [14, 16, 18, 20, 24],
    "mixed": [5, 6, 8, 10],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_exact(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"refusing to overwrite different frozen file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def right_censored_candidates(policy: dict[str, Any]) -> list[str]:
    statuses = policy.get("candidate_capacity_bound_status")
    if not isinstance(statuses, dict):
        raise ValueError("base policy lacks candidate capacity-bound statuses")
    return sorted(
        name for name, status in statuses.items()
        if status == "right_censored_lower_bound"
    )


def build_extension_manifest(
    base: dict[str, Any], workload: str, triggered: list[str]
) -> dict[str, Any]:
    base_rates = [float(value) for value in base["planned_rates_rps"]]
    extension_rates = [float(value) for value in EXTENSION_RATES[workload]]
    merged_rates = sorted(set(base_rates + extension_rates))
    manifest = dict(base)
    manifest.update(
        {
            "description": (
                f"Experiment 017 Qwen2.5-7B {workload} capacity evidence, "
                "including the preregistered right-censor extension."
            ),
            "base_seeds": list(base["seeds"]),
            "extension_seeds": EXTENSION_SEEDS,
            "seeds": list(base["seeds"]) + EXTENSION_SEEDS,
            "planned_rates_rps": merged_rates,
            "base_planned_rates_rps": base_rates,
            "extension_planned_rates_rps": extension_rates,
            "extension_candidates": triggered,
            "extension_trigger": "passed the highest observed base-grid rate in 3/3 seeds",
            "extension_early_stopping": (
                "for each triggered candidate, stop after the first extension "
                "rate that does not pass all three new seeds"
            ),
        }
    )
    return manifest


def main() -> int:
    amendment: dict[str, Any] = {
        "schema_version": 1,
        "reason": (
            "The base grid produced a lower bound for at least one candidate. "
            "This extension was frozen before observing any extension-seed outcome."
        ),
        "extension_seeds": EXTENSION_SEEDS,
        "workloads": {},
    }
    for workload in ("balanced", "mixed"):
        base_manifest_path = ROOT / "configs" / f"generalization_7b_{workload}_search.json"
        base_policy_path = ROOT / "results" / f"generalization_7b_{workload}_policy.json"
        base_manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
        base_policy = json.loads(base_policy_path.read_text(encoding="utf-8"))
        triggered = right_censored_candidates(base_policy)
        extension_manifest = build_extension_manifest(
            base_manifest, workload, triggered
        )
        extension_path = (
            ROOT / "configs" /
            f"generalization_7b_{workload}_capacity_final_search.json"
        )
        save_exact(extension_path, extension_manifest)
        amendment["workloads"][workload] = {
            "base_manifest_sha256": sha256(base_manifest_path),
            "base_policy_sha256": sha256(base_policy_path),
            "base_grid_ceiling_rps": max(base_manifest["planned_rates_rps"]),
            "triggered_candidates": triggered,
            "extension_rates_rps": EXTENSION_RATES[workload],
            "extension_manifest": str(extension_path.relative_to(ROOT)),
        }
    save_exact(
        ROOT / "results" / "generalization_7b_capacity_extension_amendment.json",
        amendment,
    )
    print(json.dumps(amendment["workloads"], indent=2))
    print("EXPERIMENT017_CAPACITY_EXTENSION_FROZEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
