#!/usr/bin/env python3
"""Scale synthetic workload SLOs from measured concurrency-one latency."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def round_up(value: float, quantum: float) -> float:
    return math.ceil(value / quantum) * quantum


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--result-dir", type=Path, default=PROJECT_ROOT / "results" / "raw"
    )
    parser.add_argument(
        "--pattern", default="calibration_c1_floor_mbt2048_seed32_*.json"
    )
    parser.add_argument("--baseline-workload", default="balanced")
    parser.add_argument("--baseline-ttft-slo-ms", type=float, default=100)
    parser.add_argument("--baseline-e2el-slo-ms", type=float, default=400)
    parser.add_argument("--ttft-quantum-ms", type=float, default=5)
    parser.add_argument("--e2el-quantum-ms", type=float, default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "workload_slo_calibration.csv",
    )
    args = parser.parse_args()

    rows = []
    for path in sorted(args.result_dir.glob(args.pattern)):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "workload_name": payload["workload_name"],
                "input_tokens": int(payload["input_tokens"]),
                "output_tokens": int(payload["output_tokens"]),
                "p99_ttft_ms": float(payload["p99_ttft_ms"]),
                "p99_e2el_ms": float(payload["p99_e2el_ms"]),
                "source": path.name,
            }
        )
    if not rows:
        parser.error(f"no calibration JSON matched {args.pattern!r}")

    try:
        baseline = next(
            row
            for row in rows
            if row["workload_name"] == args.baseline_workload
        )
    except StopIteration:
        parser.error(f"baseline workload {args.baseline_workload!r} not found")

    for row in rows:
        row["ttft_floor_ratio"] = (
            row["p99_ttft_ms"] / baseline["p99_ttft_ms"]
        )
        row["e2el_floor_ratio"] = (
            row["p99_e2el_ms"] / baseline["p99_e2el_ms"]
        )
        row["calibrated_ttft_slo_ms"] = round_up(
            args.baseline_ttft_slo_ms * row["ttft_floor_ratio"],
            args.ttft_quantum_ms,
        )
        row["calibrated_e2el_slo_ms"] = round_up(
            args.baseline_e2el_slo_ms * row["e2el_floor_ratio"],
            args.e2el_quantum_ms,
        )

    fields = list(rows[0])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    for row in sorted(rows, key=lambda item: item["workload_name"]):
        print(
            f"{row['workload_name']}: floor P99 TTFT/E2E="
            f"{row['p99_ttft_ms']:.2f}/{row['p99_e2el_ms']:.2f} ms, "
            f"calibrated SLO={row['calibrated_ttft_slo_ms']:.0f}/"
            f"{row['calibrated_e2el_slo_ms']:.0f} ms"
        )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
