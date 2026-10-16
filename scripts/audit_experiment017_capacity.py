#!/usr/bin/env python3
"""Audit Experiment 017 capacity boundaries, seed isolation and early stopping."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = ROOT / "results" / "generalization_7b_capacity"
NAME = re.compile(
    r"generalization7b_(?P<workload>balanced|mixed)_rps(?P<rate>[0-9.]+)_"
    r"mbt(?P<mbt>1024|2048)_fcfs_seed(?P<seed>[0-9]+)\.json"
)


def audit_stage(
    observations: dict[float, dict[int, bool]],
    rates: list[float],
    seeds: list[int],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows, errors = [], []
    stopped = False
    expected_seeds = set(seeds)
    for rate in rates:
        trials = observations.get(float(rate), {})
        if stopped:
            if trials:
                errors.append(f"rate {rate:g} was run after the first non-robust rate")
            continue
        if not trials:
            errors.append(f"rate {rate:g} is missing before an observed stop boundary")
            stopped = True
            continue
        if set(trials) != expected_seeds:
            errors.append(
                f"rate {rate:g} seeds={sorted(trials)} expected={sorted(expected_seeds)}"
            )
        passes = sum(bool(value) for value in trials.values())
        robust = set(trials) == expected_seeds and passes == len(expected_seeds)
        rows.append(
            {
                "rate_rps": float(rate),
                "seeds": sorted(trials),
                "passes": passes,
                "trials": len(trials),
                "robust": robust,
            }
        )
        if not robust:
            stopped = True
    return rows, errors


def load_observations(workload: str, mbt: int) -> dict[float, dict[int, bool]]:
    observations: dict[float, dict[int, bool]] = {}
    for path in sorted(RESULT_DIR.glob(f"generalization7b_{workload}_rps*_mbt{mbt}_fcfs_seed*.json")):
        match = NAME.fullmatch(path.name)
        if match is None:
            raise RuntimeError(f"unexpected capacity filename: {path.name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        rate = float(match.group("rate"))
        seed = int(match.group("seed"))
        server = payload.get("server", {})
        if (
            payload.get("model") != "qwen2.5-7b"
            or not math.isclose(float(payload.get("request_rate", -1)), rate)
            or int(payload.get("seed", -1)) != seed
            or str(server.get("max_num_batched_tokens")) != str(mbt)
            or str(server.get("max_num_seqs")) != "256"
            or server.get("scheduling_policy") != "fcfs"
            or server.get("prefix_caching") != "false"
        ):
            raise RuntimeError(f"metadata mismatch: {path}")
        if seed in observations.setdefault(rate, {}):
            raise RuntimeError(f"duplicate rate/seed evidence: {path}")
        observations[rate][seed] = bool(payload["all_classes_meet_slo"])
    return observations


def main() -> int:
    amendment = json.loads(
        (ROOT / "results/generalization_7b_capacity_extension_amendment.json").read_text()
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "valid",
        "checks": {
            "base_and_extension_seeds_disjoint": True,
            "three_complete_trials_per_observed_rate": True,
            "monotone_early_stopping_verified": True,
            "policy_capacity_recomputed_from_raw_results": True,
        },
        "workloads": {},
        "errors": [],
    }
    for workload in ("balanced", "mixed"):
        base = json.loads(
            (ROOT / "configs" / f"generalization_7b_{workload}_search.json").read_text()
        )
        final = json.loads(
            (ROOT / "configs" / f"generalization_7b_{workload}_capacity_final_search.json").read_text()
        )
        policy = json.loads(
            (ROOT / "results" / f"generalization_7b_{workload}_capacity_final_policy.json").read_text()
        )
        triggered = set(amendment["workloads"][workload]["triggered_candidates"])
        workload_report = {}
        for mbt in (1024, 2048):
            candidate = f"mbt{mbt}_fcfs"
            observations = load_observations(workload, mbt)
            base_observations = {
                rate: {seed: passed for seed, passed in trials.items() if seed in set(base["seeds"])}
                for rate, trials in observations.items()
                if any(seed in set(base["seeds"]) for seed in trials)
            }
            base_rows, errors = audit_stage(
                base_observations,
                [float(value) for value in base["planned_rates_rps"]],
                [int(value) for value in base["seeds"]],
            )
            extension_rows = []
            extension_observations = {
                rate: {seed: passed for seed, passed in trials.items() if seed in set(final["extension_seeds"])}
                for rate, trials in observations.items()
                if any(seed in set(final["extension_seeds"]) for seed in trials)
            }
            if candidate in triggered:
                extension_rows, extension_errors = audit_stage(
                    extension_observations,
                    [float(value) for value in final["extension_planned_rates_rps"]],
                    [int(value) for value in final["extension_seeds"]],
                )
                errors.extend(extension_errors)
            elif extension_observations:
                errors.append("extension evidence exists for a non-triggered candidate")
            rows = base_rows + extension_rows
            robust_rates = [row["rate_rps"] for row in rows if row["robust"]]
            capacity = max(robust_rates, default=None)
            observed_rates = [row["rate_rps"] for row in rows]
            status = (
                "no_feasible_rate" if capacity is None
                else "right_censored_lower_bound"
                if capacity == max(observed_rates)
                else "bounded_by_observed_failure"
            )
            if policy["candidate_capacities"].get(candidate) != capacity:
                errors.append("policy capacity differs from raw evidence")
            if policy["candidate_capacity_bound_status"].get(candidate) != status:
                errors.append("policy boundary status differs from raw evidence")
            workload_report[candidate] = {
                "base": base_rows,
                "extension": extension_rows,
                "recomputed_capacity_rps": capacity,
                "capacity_bound_status": status,
                "errors": errors,
            }
            report["errors"].extend(
                f"{workload}/{candidate}: {error}" for error in errors
            )
        report["workloads"][workload] = workload_report
    if report["errors"]:
        report["status"] = "invalid"
        for key in report["checks"]:
            report["checks"][key] = False
    output = ROOT / "results/generalization_7b_capacity_audit.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["errors"]:
        raise SystemExit("EXPERIMENT017_CAPACITY_AUDIT_FAILED")
    print("EXPERIMENT017_CAPACITY_AUDIT_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
