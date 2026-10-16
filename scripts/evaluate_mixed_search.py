#!/usr/bin/env python3
"""Evaluate repeated mixed-workload trials and emit a safe policy."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from slo_autotuner.mixed import load_request_classes
from slo_autotuner.mixed_search import (
    MixedCandidateSpec,
    evaluate_mixed_candidate,
    load_candidate_runs,
    select_mixed_candidate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def capacity_bound_status(
    evaluation: Any, planned_rates: list[float] | None = None
) -> str:
    """Distinguish an observed failure boundary from a passed observed ceiling.

    ``planned_rates`` is retained for call-site compatibility, but a rate that was
    merely planned is not evidence.  This matters when a run is interrupted before
    reaching the end of its grid.
    """
    capacity = evaluation.robust_capacity_rps
    if capacity is None:
        return "no_feasible_rate"
    observed_rates = [float(item.offered_rps) for item in evaluation.rates]
    if not observed_rates or float(capacity) == max(observed_rates):
        return "right_censored_lower_bound"
    return "bounded_by_observed_failure"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "configs" / "mixed_search.json",
    )
    parser.add_argument(
        "--workload-config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "mixed_workload.json",
    )
    parser.add_argument(
        "--result-dir", type=Path, default=PROJECT_ROOT / "results" / "raw"
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=PROJECT_ROOT / "results" / "mixed_search.csv",
    )
    parser.add_argument(
        "--output-policy",
        type=Path,
        default=PROJECT_ROOT / "results" / "mixed_policy.json",
    )
    parser.add_argument(
        "--workload-name",
        default="80pct_interactive_short_20pct_document_long",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    planned_rates = [float(value) for value in manifest.get("planned_rates_rps", [])]
    allowed_seeds = {int(value) for value in manifest.get("seeds", [])}
    if not allowed_seeds:
        raise SystemExit("manifest must declare at least one allowed seed")
    evidence_policy = manifest["evidence_policy"]
    min_repetitions = int(evidence_policy["min_repetitions"])
    required_pass_rate = float(evidence_policy["required_window_pass_rate"])
    request_classes = load_request_classes(args.workload_config)

    evaluations = []
    for item in manifest["candidates"]:
        if not item.get("patterns"):
            continue
        candidate = MixedCandidateSpec(
            name=item["name"],
            max_num_batched_tokens=int(item["max_num_batched_tokens"]),
            scheduling_policy=item["scheduling_policy"],
            patterns=tuple(item["patterns"]),
        )
        runs = [
            run
            for run in load_candidate_runs(args.result_dir, candidate, request_classes)
            if run.seed in allowed_seeds
        ]
        if not runs:
            raise SystemExit(f"no results found for candidate {candidate.name}")
        evaluations.append(
            evaluate_mixed_candidate(
                candidate,
                runs,
                request_classes,
                min_repetitions,
                required_pass_rate,
            )
        )

    selected = select_mixed_candidate(evaluations, request_classes)
    rows: list[dict[str, Any]] = []
    for evaluation in evaluations:
        for aggregate in evaluation.rates:
            row: dict[str, Any] = {
                "candidate": evaluation.candidate.name,
                "offered_rps": aggregate.offered_rps,
                "trials": aggregate.trials,
                "feasible_trials": aggregate.feasible_trials,
                "pass_rate": aggregate.pass_rate,
                "pass_rate_ci95_low": aggregate.pass_rate_ci95_low,
                "pass_rate_ci95_high": aggregate.pass_rate_ci95_high,
                "mean_throughput_rps": aggregate.mean_throughput_rps,
                "mean_goodput_rps": aggregate.mean_goodput_rps,
                "min_goodput_rps": aggregate.min_goodput_rps,
                "robustly_feasible": aggregate.robustly_feasible(
                    min_repetitions, required_pass_rate
                ),
            }
            for request_class in request_classes:
                name = request_class.name
                row[f"{name}_worst_p99_ttft_ms"] = (
                    aggregate.worst_p99_ttft_ms[name]
                )
                row[f"{name}_worst_p99_e2el_ms"] = (
                    aggregate.worst_p99_e2el_ms[name]
                )
            rows.append(row)

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    robust_evaluations = [
        item for item in evaluations if item.robust_capacity_rps is not None
    ]
    rollback = next(
        (
            item
            for item in robust_evaluations
            if selected is not None and item.candidate.name != selected.candidate.name
        ),
        None,
    )

    def policy_entry(evaluation: Any) -> dict[str, Any] | None:
        if evaluation is None or evaluation.robust_capacity_rps is None:
            return None
        capacity = evaluation.robust_capacity_rps
        aggregate = evaluation.aggregate_at(capacity)
        return {
            "candidate": evaluation.candidate.name,
            "max_num_batched_tokens": (
                evaluation.candidate.max_num_batched_tokens
            ),
            "scheduling_policy": evaluation.candidate.scheduling_policy,
            "admission_limit_rps": capacity,
            "capacity_bound_status": capacity_bound_status(
                evaluation, planned_rates
            ),
            "evidence": {
                "trials": aggregate.trials,
                "feasible_trials": aggregate.feasible_trials,
                "worst_p99_ttft_ms": aggregate.worst_p99_ttft_ms,
                "worst_p99_e2el_ms": aggregate.worst_p99_e2el_ms,
                "min_goodput_rps": aggregate.min_goodput_rps,
            },
        }

    policy = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workload": args.workload_name,
        "status": "ready" if selected is not None else "insufficient_evidence",
        "evidence_policy": evidence_policy,
        "class_slos": [asdict(item) for item in request_classes],
        "selected": policy_entry(selected),
        "rollback": policy_entry(rollback),
        "selection_rule": (
            "highest robust capacity, then lowest worst normalized class E2E "
            "ratio, then mean goodput"
        ),
        "candidate_capacities": {
            item.candidate.name: item.robust_capacity_rps for item in evaluations
        },
        "candidate_capacity_bound_status": {
            item.candidate.name: capacity_bound_status(item, planned_rates)
            for item in evaluations
        },
    }
    args.output_policy.write_text(
        json.dumps(policy, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    for row in rows:
        print(
            f"{row['candidate']} rate={row['offered_rps']:g}: "
            f"pass={row['feasible_trials']}/{row['trials']} "
            f"robust={row['robustly_feasible']}"
        )
    if selected is None:
        print("selected=none")
    else:
        print(
            f"selected={selected.candidate.name} "
            f"capacity={selected.robust_capacity_rps:g} req/s"
        )
    print(f"Wrote {args.output_csv}")
    print(f"Wrote {args.output_policy}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
