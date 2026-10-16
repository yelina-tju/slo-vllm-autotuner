#!/usr/bin/env python3
"""Freeze model-specific SLOs from preregistered low-load calibration runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_runs(paths: Iterable[Path], expected_seeds: set[int]) -> list[tuple[Path, dict]]:
    runs = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        runs.append((path, payload))
    if not runs:
        raise ValueError("no low-load calibration files were supplied")

    seeds = [int(payload["seed"]) for _, payload in runs]
    if len(seeds) != len(set(seeds)):
        raise ValueError(f"calibration seeds must be unique, got {seeds}")
    if set(seeds) != expected_seeds:
        raise ValueError(
            f"expected calibration seeds {sorted(expected_seeds)}, got {sorted(seeds)}"
        )

    models = {str(payload["model"]) for _, payload in runs}
    if len(models) != 1:
        raise ValueError(f"all runs must use one model alias, got {sorted(models)}")
    for path, payload in runs:
        if not math.isclose(float(payload["request_rate"]), 1.0):
            raise ValueError(f"{path}: expected preregistered 1 req/s low-load run")
        if int(payload.get("failed", 0)) != 0:
            raise ValueError(f"{path}: low-load run contains failed requests")
    return runs


def derive(
    runs: list[tuple[Path, dict]],
    ttft_factor: float = 3.0,
    e2el_factor: float = 1.4,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if ttft_factor <= 0 or e2el_factor <= 0:
        raise ValueError("SLO factors must be positive")

    reference_specs = runs[0][1]["class_specs"]
    reference_shape = {
        item["name"]: {
            key: item[key]
            for key in ("weight", "input_tokens", "output_tokens", "priority")
        }
        for item in reference_specs
    }
    if not reference_shape:
        raise ValueError("calibration result has no request classes")

    evidence_classes: dict[str, Any] = {}
    output_classes = []
    for name, shape in reference_shape.items():
        observations = []
        for path, payload in runs:
            candidate_shape = next(
                (item for item in payload["class_specs"] if item["name"] == name), None
            )
            if candidate_shape is None:
                raise ValueError(f"{path}: missing class {name}")
            candidate_shape = {
                key: candidate_shape[key]
                for key in ("weight", "input_tokens", "output_tokens", "priority")
            }
            if candidate_shape != shape:
                raise ValueError(f"{path}: class shape changed for {name}")
            summary = payload["classes"][name]
            ttft = float(summary["p99_ttft_ms"])
            e2el = float(summary["p99_e2el_ms"])
            if not all(math.isfinite(value) and value > 0 for value in (ttft, e2el)):
                raise ValueError(f"{path}: invalid P99 for {name}")
            observations.append(
                {
                    "seed": int(payload["seed"]),
                    "p99_ttft_ms": ttft,
                    "p99_e2el_ms": e2el,
                }
            )

        max_ttft = max(item["p99_ttft_ms"] for item in observations)
        max_e2el = max(item["p99_e2el_ms"] for item in observations)
        ttft_slo = ttft_factor * max_ttft
        e2el_slo = e2el_factor * max_e2el
        output_classes.append(
            {
                "name": name,
                **shape,
                "ttft_slo_ms": ttft_slo,
                "e2el_slo_ms": e2el_slo,
            }
        )
        evidence_classes[name] = {
            "observations": sorted(observations, key=lambda item: item["seed"]),
            "max_p99_ttft_ms": max_ttft,
            "max_p99_e2el_ms": max_e2el,
            "ttft_slo_ms": ttft_slo,
            "e2el_slo_ms": e2el_slo,
        }

    config = {
        "description": (
            "Qwen2.5-7B low-load-calibrated SLO classes. Thresholds are frozen "
            "before capacity search according to Experiment 017."
        ),
        "classes": output_classes,
    }
    evidence = {
        "schema_version": 1,
        "method": {
            "ttft_slo": "3.0 * max_seed(p99_ttft_ms)",
            "e2el_slo": "1.4 * max_seed(p99_e2el_ms)",
            "ttft_factor": ttft_factor,
            "e2el_factor": e2el_factor,
            "request_rate_rps": 1.0,
        },
        "model": runs[0][1]["model"],
        "seeds": sorted(int(payload["seed"]) for _, payload in runs),
        "source_files": [
            {"path": str(path), "sha256": sha256(path)} for path, _ in runs
        ],
        "classes": evidence_classes,
    }
    return config, evidence


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(f"refusing to overwrite different frozen evidence: {path}")
        return
    path.write_text(rendered, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+", type=Path, required=True)
    parser.add_argument("--expected-seeds", nargs="+", type=int, required=True)
    parser.add_argument("--ttft-factor", type=float, default=3.0)
    parser.add_argument("--e2el-factor", type=float, default=1.4)
    parser.add_argument(
        "--output-config",
        type=Path,
        default=ROOT / "configs" / "generalization_7b_workload.json",
    )
    parser.add_argument(
        "--output-evidence",
        type=Path,
        default=ROOT / "results" / "generalization_7b_slo_evidence.json",
    )
    args = parser.parse_args()
    runs = load_runs(args.inputs, set(args.expected_seeds))
    config, evidence = derive(runs, args.ttft_factor, args.e2el_factor)
    write_new(args.output_config, config)
    write_new(args.output_evidence, evidence)
    print(f"frozen_config={args.output_config}")
    print(f"evidence={args.output_evidence}")
    for item in config["classes"]:
        print(
            f"{item['name']}: TTFT/E2E SLO="
            f"{item['ttft_slo_ms']:.3f}/{item['e2el_slo_ms']:.3f} ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
