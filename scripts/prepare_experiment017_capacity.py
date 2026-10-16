#!/usr/bin/env python3
"""Freeze Experiment 017 balanced/mixed capacity-search manifests."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SLO_CONFIG = ROOT / "configs" / "generalization_7b_workload.json"
SLO_EVIDENCE = ROOT / "results" / "generalization_7b_slo_evidence.json"
SEEDS = [111, 112, 113]
CANDIDATES = [1024, 2048]
RATE_GRIDS = {
    "balanced": [1, 2, 4, 6, 8, 10, 12],
    "mixed": [1, 1.5, 2, 2.5, 3, 4],
}


def save_exact(path: Path, payload: dict) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"refusing to overwrite different frozen file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def candidate(name: str, mbt: int) -> dict:
    return {
        "name": name,
        "max_num_batched_tokens": mbt,
        "scheduling_policy": "fcfs",
        "patterns": [f"generalization7b_{{workload}}_rps*_mbt{mbt}_fcfs_seed*.json"],
    }


def main() -> int:
    workload = json.loads(SLO_CONFIG.read_text(encoding="utf-8"))
    evidence = json.loads(SLO_EVIDENCE.read_text(encoding="utf-8"))
    classes = {item["name"]: item for item in workload["classes"]}
    if set(classes) != {"interactive_short", "document_long"}:
        raise RuntimeError("frozen 7B SLO config has an unexpected class set")
    for name, item in classes.items():
        expected = evidence["classes"][name]
        if (
            item["ttft_slo_ms"] != expected["ttft_slo_ms"]
            or item["e2el_slo_ms"] != expected["e2el_slo_ms"]
        ):
            raise RuntimeError(f"frozen SLO/evidence mismatch for {name}")

    balanced_class = dict(classes["interactive_short"])
    balanced_class["weight"] = 1.0
    balanced = {
        "description": "Experiment 017 frozen 7B balanced capacity workload.",
        "classes": [balanced_class],
    }
    mixed = {
        "description": "Experiment 017 frozen 7B 80/20 mixed capacity workload.",
        "classes": list(classes.values()),
    }
    save_exact(ROOT / "configs" / "generalization_7b_balanced.json", balanced)
    save_exact(ROOT / "configs" / "generalization_7b_mixed.json", mixed)

    for workload_name in ("balanced", "mixed"):
        manifest = {
            "description": (
                f"Experiment 017 preregistered Qwen2.5-7B {workload_name} "
                "ascending capacity search with monotone early stopping."
            ),
            "model": "qwen2.5-7b",
            "seeds": SEEDS,
            "planned_rates_rps": RATE_GRIDS[workload_name],
            "early_stopping": (
                "stop higher rates for a candidate after the first rate that "
                "does not pass all three seeds"
            ),
            "evidence_policy": {
                "min_repetitions": 3,
                "required_window_pass_rate": 1.0,
            },
            "candidates": [
                {
                    **candidate(f"mbt{mbt}_fcfs", mbt),
                    "patterns": [
                        f"generalization7b_{workload_name}_rps*_mbt{mbt}_fcfs_seed*.json"
                    ],
                }
                for mbt in CANDIDATES
            ],
        }
        save_exact(
            ROOT / "configs" / f"generalization_7b_{workload_name}_search.json",
            manifest,
        )
    print("EXPERIMENT017_CAPACITY_MANIFESTS_FROZEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
