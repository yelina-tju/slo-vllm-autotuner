#!/usr/bin/env python3
"""Aggregate repeated Poisson experiments and choose an empirical safe rate."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from slo_autotuner.open_loop import (  # noqa: E402
    aggregate_by_rate,
    load_open_loop_runs,
    select_empirically_safe_rate,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--result-dir", type=Path, default=PROJECT_ROOT / "results" / "raw"
    )
    parser.add_argument("--pattern", default="poisson_*boundary*.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "poisson_boundary_aggregate.csv",
    )
    parser.add_argument("--max-p99-ttft-ms", type=float, default=100.0)
    parser.add_argument("--max-p99-e2el-ms", type=float, default=400.0)
    parser.add_argument("--min-repetitions", type=int, default=3)
    parser.add_argument("--required-pass-rate", type=float, default=1.0)
    parser.add_argument("--ttft-safety-margin-ms", type=float, default=0.0)
    parser.add_argument("--e2el-safety-margin-ms", type=float, default=0.0)
    args = parser.parse_args()

    runs = load_open_loop_runs(
        args.result_dir,
        pattern=args.pattern,
        max_request_ttft_ms=args.max_p99_ttft_ms,
        max_request_e2el_ms=args.max_p99_e2el_ms,
    )
    if not runs:
        parser.error(f"no benchmark JSON matched {args.pattern!r}")

    aggregates = aggregate_by_rate(
        runs,
        max_p99_ttft_ms=args.max_p99_ttft_ms,
        max_p99_e2el_ms=args.max_p99_e2el_ms,
    )
    selected = select_empirically_safe_rate(
        aggregates,
        min_repetitions=args.min_repetitions,
        required_pass_rate=args.required_pass_rate,
        max_p99_ttft_ms=args.max_p99_ttft_ms,
        max_p99_e2el_ms=args.max_p99_e2el_ms,
        ttft_safety_margin_ms=args.ttft_safety_margin_ms,
        e2el_safety_margin_ms=args.e2el_safety_margin_ms,
    )

    fields = [
        "offered_rps",
        "trials",
        "feasible_trials",
        "pass_rate",
        "pass_rate_ci95_low",
        "pass_rate_ci95_high",
        "mean_achieved_rps",
        "mean_goodput_rps",
        "min_goodput_rps",
        "mean_request_compliance_rate",
        "worst_p99_ttft_ms",
        "worst_p99_e2el_ms",
        "ttft_headroom_ms",
        "e2el_headroom_ms",
        "empirically_safe",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for aggregate in aggregates:
            writer.writerow(
                {
                    "offered_rps": aggregate.offered_rps,
                    "trials": aggregate.trials,
                    "feasible_trials": aggregate.feasible_trials,
                    "pass_rate": aggregate.pass_rate,
                    "pass_rate_ci95_low": aggregate.pass_rate_ci95_low,
                    "pass_rate_ci95_high": aggregate.pass_rate_ci95_high,
                    "mean_achieved_rps": aggregate.mean_achieved_rps,
                    "mean_goodput_rps": aggregate.mean_goodput_rps,
                    "min_goodput_rps": aggregate.min_goodput_rps,
                    "mean_request_compliance_rate": (
                        aggregate.mean_request_compliance_rate
                    ),
                    "worst_p99_ttft_ms": aggregate.worst_p99_ttft_ms,
                    "worst_p99_e2el_ms": aggregate.worst_p99_e2el_ms,
                    "ttft_headroom_ms": (
                        args.max_p99_ttft_ms - aggregate.worst_p99_ttft_ms
                    ),
                    "e2el_headroom_ms": (
                        args.max_p99_e2el_ms - aggregate.worst_p99_e2el_ms
                    ),
                    "empirically_safe": aggregate.empirically_safe(
                        min_repetitions=args.min_repetitions,
                        required_pass_rate=args.required_pass_rate,
                        max_p99_ttft_ms=args.max_p99_ttft_ms,
                        max_p99_e2el_ms=args.max_p99_e2el_ms,
                        ttft_safety_margin_ms=args.ttft_safety_margin_ms,
                        e2el_safety_margin_ms=args.e2el_safety_margin_ms,
                    ),
                }
            )

    if selected is None:
        print("No rate satisfies the repeated-measurement safety policy.")
        print(f"Wrote {args.output}")
        return 2

    print(
        f"Selected empirical safe rate={selected.offered_rps:.2f} req/s: "
        f"passes={selected.feasible_trials}/{selected.trials}, "
        f"mean goodput={selected.mean_goodput_rps:.2f} req/s, "
        f"worst P99 E2E={selected.worst_p99_e2el_ms:.2f} ms"
    )
    print(
        "Observed pass-probability 95% Wilson interval: "
        f"[{selected.pass_rate_ci95_low:.3f}, "
        f"{selected.pass_rate_ci95_high:.3f}]"
    )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
