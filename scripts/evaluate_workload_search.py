#!/usr/bin/env python3
"""Evaluate capacity and configuration evidence for multiple workloads."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from slo_autotuner.search import (  # noqa: E402
    CandidateSpec,
    classify_rate,
    evaluate_candidate_runs,
    load_candidate_runs,
    select_candidate,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "configs" / "workload_search.json",
    )
    parser.add_argument(
        "--result-dir", type=Path, default=PROJECT_ROOT / "results" / "raw"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "workload_search.csv",
    )
    parser.add_argument(
        "--policy-output",
        type=Path,
        default=PROJECT_ROOT / "results" / "workload_policy.json",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    evidence_policy = manifest["evidence_policy"]
    output_rows = []
    policy_rows = []

    for workload in manifest["workloads"]:
        thresholds = {
            "max_p99_ttft_ms": workload["max_p99_ttft_ms"],
            "max_p99_e2el_ms": workload["max_p99_e2el_ms"],
        }
        full_policy = {**evidence_policy, **thresholds}
        evaluations = []
        runs_by_candidate = {}

        for item in workload["candidates"]:
            candidate = CandidateSpec(
                name=item["name"],
                max_num_batched_tokens=int(item["max_num_batched_tokens"]),
                max_num_seqs=int(item["max_num_seqs"]),
                patterns=tuple(item["patterns"]),
            )
            runs = load_candidate_runs(
                args.result_dir,
                candidate,
                max_request_ttft_ms=thresholds["max_p99_ttft_ms"],
                max_request_e2el_ms=thresholds["max_p99_e2el_ms"],
            )
            for run in runs:
                if run.workload_name not in {None, workload["name"]}:
                    raise ValueError(
                        f"{run.source}: workload metadata does not match "
                        f"{workload['name']}"
                    )
                if run.input_tokens not in {None, workload["input_tokens"]}:
                    raise ValueError(f"{run.source}: input length mismatch")
                if run.output_tokens not in {None, workload["output_tokens"]}:
                    raise ValueError(f"{run.source}: output length mismatch")
            if not runs:
                continue
            runs_by_candidate[candidate.name] = runs
            evaluation = evaluate_candidate_runs(
                candidate, runs, **full_policy
            )
            evaluations.append(evaluation)
            for aggregate in evaluation.rates:
                output_rows.append(
                    {
                        "workload": workload["name"],
                        "input_tokens": workload["input_tokens"],
                        "output_tokens": workload["output_tokens"],
                        "ttft_slo_ms": workload["max_p99_ttft_ms"],
                        "e2el_slo_ms": workload["max_p99_e2el_ms"],
                        "candidate": candidate.name,
                        "offered_rps": aggregate.offered_rps,
                        "trials": aggregate.trials,
                        "feasible_trials": aggregate.feasible_trials,
                        "pass_rate": aggregate.pass_rate,
                        "evidence_status": classify_rate(
                            aggregate, **full_policy
                        ),
                        "mean_goodput_rps": aggregate.mean_goodput_rps,
                        "mean_p99_e2el_ms": aggregate.mean_p99_e2el_ms,
                        "worst_p99_e2el_ms": aggregate.worst_p99_e2el_ms,
                    }
                )

        selected, is_robust = select_candidate(evaluations)
        robust_selected = selected if selected is not None and is_robust else None
        compatible_candidates = []
        if robust_selected is not None:
            selected_capacity = robust_selected.robust_capacity_rps
            assert selected_capacity is not None
            for evaluation in evaluations:
                if (
                    evaluation.candidate.name
                    == robust_selected.candidate.name
                    or evaluation.robust_capacity_rps != selected_capacity
                ):
                    continue
                aggregate = evaluation.aggregate_at(selected_capacity)
                compatible_candidates.append(
                    {
                        "candidate": evaluation.candidate.name,
                        "robust_capacity_rps": selected_capacity,
                        "status": "ready",
                        "evidence": {
                            "trials": aggregate.trials,
                            "feasible_trials": aggregate.feasible_trials,
                            "worst_p99_ttft_ms": aggregate.worst_p99_ttft_ms,
                            "worst_p99_e2el_ms": aggregate.worst_p99_e2el_ms,
                        },
                    }
                )
        policy_rows.append(
            {
                "workload": workload["name"],
                "selected_candidate": (
                    robust_selected.candidate.name if robust_selected else None
                ),
                "robust_capacity_rps": (
                    robust_selected.robust_capacity_rps
                    if robust_selected
                    else None
                ),
                "status": "ready" if robust_selected else "insufficient_evidence",
                "compatible_candidates": compatible_candidates,
            }
        )
        print(f"\n[{workload['name']}]")
        for evaluation in evaluations:
            print(
                f"{evaluation.candidate.name}: "
                f"robust={evaluation.robust_capacity_rps}, "
                f"observed={evaluation.observed_capacity_rps}"
            )
        if robust_selected:
            print(
                f"policy selects {robust_selected.candidate.name} at "
                f"{robust_selected.robust_capacity_rps} req/s"
            )
        else:
            print("policy selection withheld: insufficient repeated evidence")

        comparison_rate = float(workload["paired_comparison_rate"])
        if len(runs_by_candidate) >= 2:
            first_name, second_name = list(runs_by_candidate)[:2]
            first_by_seed = {
                run.seed: run
                for run in runs_by_candidate[first_name]
                if run.offered_rps == comparison_rate and run.seed is not None
            }
            second_by_seed = {
                run.seed: run
                for run in runs_by_candidate[second_name]
                if run.offered_rps == comparison_rate and run.seed is not None
            }
            common_seeds = sorted(first_by_seed.keys() & second_by_seed.keys())
            if common_seeds:
                deltas = [
                    first_by_seed[seed].p99_e2el_ms
                    - second_by_seed[seed].p99_e2el_ms
                    for seed in common_seeds
                ]
                print(
                    f"paired P99 E2E ({first_name} - {second_name}) at "
                    f"{comparison_rate:g} req/s: seeds={common_seeds}, "
                    f"deltas={[round(value, 2) for value in deltas]}, "
                    f"mean={sum(deltas) / len(deltas):.2f} ms"
                )

    fields = list(output_rows[0])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)
    args.policy_output.write_text(
        json.dumps({"policies": policy_rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {args.output}")
    print(f"Wrote {args.policy_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
