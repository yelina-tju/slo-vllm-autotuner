"""Offline selection over measured vLLM benchmark results.

This is the first, deliberately small, autotuner: reject configurations that
violate the tail-latency SLO and maximize output-token throughput among the
remaining configurations.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class BenchmarkRun:
    source: Path
    concurrency: int
    completed: int
    failed: int
    request_throughput: float
    output_throughput: float
    p99_ttft_ms: float
    p99_tpot_ms: float
    p99_e2el_ms: float

    @classmethod
    def from_json(cls, path: Path) -> "BenchmarkRun":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            source=path,
            concurrency=int(payload["max_concurrency"]),
            completed=int(payload["completed"]),
            failed=int(payload["failed"]),
            request_throughput=float(payload["request_throughput"]),
            output_throughput=float(payload["output_throughput"]),
            p99_ttft_ms=float(payload["p99_ttft_ms"]),
            p99_tpot_ms=float(payload["p99_tpot_ms"]),
            p99_e2el_ms=float(payload["p99_e2el_ms"]),
        )

    def meets_slo(self, max_p99_ttft_ms: float, max_p99_e2el_ms: float) -> bool:
        return (
            self.failed == 0
            and self.p99_ttft_ms <= max_p99_ttft_ms
            and self.p99_e2el_ms <= max_p99_e2el_ms
        )


def load_runs(result_dir: Path, pattern: str = "steady_*.json") -> list[BenchmarkRun]:
    """Load steady-state runs in ascending concurrency order."""
    return sorted(
        (BenchmarkRun.from_json(path) for path in result_dir.glob(pattern)),
        key=lambda run: run.concurrency,
    )


def select_best_run(
    runs: Iterable[BenchmarkRun],
    max_p99_ttft_ms: float,
    max_p99_e2el_ms: float,
) -> BenchmarkRun | None:
    """Return the highest-throughput run that satisfies every SLO."""
    feasible = [
        run
        for run in runs
        if run.meets_slo(max_p99_ttft_ms, max_p99_e2el_ms)
    ]
    return max(feasible, key=lambda run: run.output_throughput, default=None)

