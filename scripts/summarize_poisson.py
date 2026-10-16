#!/usr/bin/env python3
"""Summarize open-loop runs and select the best SLO-feasible window."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from slo_autotuner.open_loop import (  # noqa: E402
    load_open_loop_runs,
    select_best_open_loop_run,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--result-dir", type=Path, default=PROJECT_ROOT / "results" / "raw"
    )
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "results" / "poisson_summary.csv"
    )
    parser.add_argument("--pattern", default="poisson_*.json")
    parser.add_argument("--max-p99-ttft-ms", type=float, default=100.0)
    parser.add_argument("--max-p99-e2el-ms", type=float, default=400.0)
    args = parser.parse_args()

    runs = load_open_loop_runs(
        args.result_dir,
        pattern=args.pattern,
        max_request_ttft_ms=args.max_p99_ttft_ms,
        max_request_e2el_ms=args.max_p99_e2el_ms,
    )
    if not runs:
        parser.error(f"no open-loop benchmark JSON found in {args.result_dir}")

    fields = [
        "source",
        "offered_rps",
        "completed",
        "failed",
        "achieved_rps",
        "request_goodput_rps",
        "request_compliance_rate",
        "p99_ttft_ms",
        "p99_e2el_ms",
        "ttft_violations",
        "e2el_violations",
        "any_slo_violations",
        "window_slo_feasible",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for run in runs:
            writer.writerow(
                {
                    "source": run.source.name,
                    "offered_rps": run.offered_rps,
                    "completed": run.completed,
                    "failed": run.failed,
                    "achieved_rps": run.achieved_rps,
                    "request_goodput_rps": run.request_goodput_rps,
                    "request_compliance_rate": run.request_compliance_rate,
                    "p99_ttft_ms": run.p99_ttft_ms,
                    "p99_e2el_ms": run.p99_e2el_ms,
                    "ttft_violations": run.ttft_violations,
                    "e2el_violations": run.e2el_violations,
                    "any_slo_violations": run.any_slo_violations,
                    "window_slo_feasible": run.window_meets_slo(
                        args.max_p99_ttft_ms, args.max_p99_e2el_ms
                    ),
                }
            )

    best = select_best_open_loop_run(
        runs,
        max_p99_ttft_ms=args.max_p99_ttft_ms,
        max_p99_e2el_ms=args.max_p99_e2el_ms,
    )
    if best is None:
        print("No measured open-loop window satisfies the requested SLO.")
        return 2

    print(
        f"Selected {best.source.name}: offered={best.offered_rps:.2f} req/s, "
        f"goodput={best.request_goodput_rps:.2f} req/s, "
        f"P99 TTFT={best.p99_ttft_ms:.2f} ms, "
        f"P99 E2E={best.p99_e2el_ms:.2f} ms"
    )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
