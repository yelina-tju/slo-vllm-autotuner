#!/usr/bin/env python3
"""Flatten mixed-workload JSON results into an auditable CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def candidate_name(payload: dict[str, Any], source: Path) -> str:
    server = payload.get("server", {})
    max_tokens = str(server.get("max_num_batched_tokens", "unknown"))
    policy = str(server.get("scheduling_policy", "unknown"))
    if policy == "unknown":
        policy = (
            "priority"
            if payload.get("class_priority_enabled") or "priority" in source.name
            else "fcfs"
        )
    suffix = "_class_priority" if payload.get("class_priority_enabled") else ""
    return f"mbt{max_tokens}_{policy}{suffix}"


def result_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidate = candidate_name(payload, path)
    rows = []
    for class_name, summary in payload["classes"].items():
        rows.append(
            {
                "source": path.name,
                "candidate": candidate,
                "request_rate": float(payload["request_rate"]),
                "seed": int(payload["seed"]),
                "num_prompts": int(payload["num_prompts"]),
                "class_name": class_name,
                "input_tokens": int(summary["input_tokens"]),
                "output_tokens": int(summary["output_tokens"]),
                "completed": int(summary["completed"]),
                "failed": int(summary["failed"]),
                "p99_ttft_ms": float(summary["p99_ttft_ms"]),
                "ttft_slo_ms": float(summary["ttft_slo_ms"]),
                "p99_e2el_ms": float(summary["p99_e2el_ms"]),
                "e2el_slo_ms": float(summary["e2el_slo_ms"]),
                "compliance_rate": float(summary["compliance_rate"]),
                "class_window_meets_slo": bool(summary["window_meets_slo"]),
                "all_classes_meet_slo": bool(payload["all_classes_meet_slo"]),
                "request_throughput": float(payload["request_throughput"]),
                "request_goodput": float(payload["request_goodput"]),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--result-dir", type=Path, default=PROJECT_ROOT / "results" / "raw"
    )
    parser.add_argument("--pattern", default="mixed_rps*_seed*.json")
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "results" / "mixed_summary.csv"
    )
    args = parser.parse_args()

    paths = sorted(
        path
        for path in args.result_dir.glob(args.pattern)
        if "_invalid_" not in path.name
    )
    if not paths:
        parser.error(f"no files matched {args.pattern!r}")
    rows = [row for path in paths for row in result_rows(path)]
    rows.sort(
        key=lambda row: (
            row["candidate"],
            row["request_rate"],
            row["class_name"],
        )
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    seen: set[tuple[str, float, str]] = set()
    for row in rows:
        key = (row["candidate"], row["request_rate"], row["source"])
        if key not in seen:
            print(
                f"{row['candidate']} rate={row['request_rate']:g} "
                f"all_classes_meet_slo={row['all_classes_meet_slo']}"
            )
            seen.add(key)
        print(
            f"  {row['class_name']}: P99 TTFT/E2E="
            f"{row['p99_ttft_ms']:.2f}/{row['p99_e2el_ms']:.2f} ms, "
            f"compliance={row['compliance_rate']:.1%}"
        )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
