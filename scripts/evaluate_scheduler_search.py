#!/usr/bin/env python3
"""Evaluate scheduler candidates without overstating sparse evidence."""

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
        default=PROJECT_ROOT / "configs" / "scheduler_trials.json",
    )
    parser.add_argument(
        "--result-dir", type=Path, default=PROJECT_ROOT / "results" / "raw"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "scheduler_search.csv",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    policy = manifest["policy"]
    candidates = [
        CandidateSpec(
            name=item["name"],
            max_num_batched_tokens=int(item["max_num_batched_tokens"]),
            max_num_seqs=int(item["max_num_seqs"]),
            patterns=tuple(item["patterns"]),
        )
        for item in manifest["candidates"]
    ]

    evaluations = []
    for candidate in candidates:
        runs = load_candidate_runs(
            args.result_dir,
            candidate,
            max_request_ttft_ms=policy["max_p99_ttft_ms"],
            max_request_e2el_ms=policy["max_p99_e2el_ms"],
        )
        if not runs:
            parser.error(f"no result files matched candidate {candidate.name}")
        evaluations.append(
            evaluate_candidate_runs(candidate, runs, **policy)
        )

    fields = [
        "candidate",
        "max_num_batched_tokens",
        "max_num_seqs",
        "offered_rps",
        "trials",
        "feasible_trials",
        "pass_rate",
        "evidence_status",
        "mean_goodput_rps",
        "worst_p99_ttft_ms",
        "worst_p99_e2el_ms",
        "e2el_headroom_ms",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for evaluation in evaluations:
            for aggregate in evaluation.rates:
                writer.writerow(
                    {
                        "candidate": evaluation.candidate.name,
                        "max_num_batched_tokens": (
                            evaluation.candidate.max_num_batched_tokens
                        ),
                        "max_num_seqs": evaluation.candidate.max_num_seqs,
                        "offered_rps": aggregate.offered_rps,
                        "trials": aggregate.trials,
                        "feasible_trials": aggregate.feasible_trials,
                        "pass_rate": aggregate.pass_rate,
                        "evidence_status": classify_rate(
                            aggregate, **policy
                        ),
                        "mean_goodput_rps": aggregate.mean_goodput_rps,
                        "worst_p99_ttft_ms": aggregate.worst_p99_ttft_ms,
                        "worst_p99_e2el_ms": aggregate.worst_p99_e2el_ms,
                        "e2el_headroom_ms": (
                            policy["max_p99_e2el_ms"]
                            - aggregate.worst_p99_e2el_ms
                        ),
                    }
                )

    selected, is_robust = select_candidate(evaluations)
    for evaluation in evaluations:
        print(
            f"{evaluation.candidate.name}: "
            f"robust_capacity={evaluation.robust_capacity_rps}, "
            f"observed_capacity={evaluation.observed_capacity_rps}"
        )
    if selected is None:
        print("No candidate has passed even one measured rate.")
        return 2

    label = "robust" if is_robust else "provisional"
    capacity = (
        selected.robust_capacity_rps
        if is_robust
        else selected.observed_capacity_rps
    )
    print(
        f"Selected {label} candidate={selected.candidate.name} "
        f"at capacity={capacity} req/s"
    )
    if not is_robust:
        print(
            "Selection is not deployment evidence: collect repetitions at "
            "the provisional boundary before promoting it."
        )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
