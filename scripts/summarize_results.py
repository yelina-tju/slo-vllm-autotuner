#!/usr/bin/env python3
"""Build a compact CSV and select the best SLO-feasible configuration."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from slo_autotuner.offline import load_runs, select_best_run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=PROJECT_ROOT / "results" / "raw",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "summary.csv",
    )
    parser.add_argument("--max-p99-ttft-ms", type=float, default=100.0)
    parser.add_argument("--max-p99-e2el-ms", type=float, default=400.0)
    args = parser.parse_args()

    runs = load_runs(args.result_dir)
    if not runs:
        parser.error(f"no steady benchmark JSON found in {args.result_dir}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "concurrency",
        "completed",
        "failed",
        "request_throughput",
        "output_throughput",
        "p99_ttft_ms",
        "p99_tpot_ms",
        "p99_e2el_ms",
        "slo_feasible",
    ]
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for run in runs:
            writer.writerow(
                {
                    "concurrency": run.concurrency,
                    "completed": run.completed,
                    "failed": run.failed,
                    "request_throughput": run.request_throughput,
                    "output_throughput": run.output_throughput,
                    "p99_ttft_ms": run.p99_ttft_ms,
                    "p99_tpot_ms": run.p99_tpot_ms,
                    "p99_e2el_ms": run.p99_e2el_ms,
                    "slo_feasible": run.meets_slo(
                        args.max_p99_ttft_ms, args.max_p99_e2el_ms
                    ),
                }
            )

    best = select_best_run(
        runs,
        max_p99_ttft_ms=args.max_p99_ttft_ms,
        max_p99_e2el_ms=args.max_p99_e2el_ms,
    )
    if best is None:
        print("No measured configuration satisfies the requested SLO.")
        return 2

    print(
        "Selected concurrency="
        f"{best.concurrency}: output={best.output_throughput:.2f} tok/s, "
        f"P99 TTFT={best.p99_ttft_ms:.2f} ms, "
        f"P99 E2E={best.p99_e2el_ms:.2f} ms"
    )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

