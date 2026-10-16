"""Analysis and selection for open-loop vLLM serving experiments."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from statistics import mean
from typing import Iterable


@dataclass(frozen=True)
class OpenLoopRun:
    """One open-loop benchmark window and its request-level SLO counts."""

    source: Path
    offered_rps: float
    completed: int
    failed: int
    achieved_rps: float
    request_goodput_rps: float
    p99_ttft_ms: float
    p99_e2el_ms: float
    ttft_violations: int
    e2el_violations: int
    any_slo_violations: int
    seed: int | None = None
    server_prefix_caching: bool | None = None
    server_max_num_batched_tokens: int | None = None
    server_max_num_seqs: int | None = None
    workload_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    configured_ttft_slo_ms: float | None = None
    configured_e2el_slo_ms: float | None = None

    @classmethod
    def from_json(
        cls,
        path: Path,
        max_request_ttft_ms: float = 100.0,
        max_request_e2el_ms: float = 400.0,
    ) -> "OpenLoopRun":
        payload = json.loads(path.read_text(encoding="utf-8"))
        ttfts_ms = [float(value) * 1000.0 for value in payload.get("ttfts", [])]
        itls = payload.get("itls", [])

        if len(ttfts_ms) != len(itls):
            raise ValueError(
                f"{path}: ttfts and itls have different request counts"
            )

        # vLLM stores TTFT and per-token gaps in seconds. End-to-end latency is
        # TTFT plus every subsequent inter-token latency for that request.
        e2els_ms = [
            ttft_ms + sum(float(gap) for gap in request_itls) * 1000.0
            for ttft_ms, request_itls in zip(ttfts_ms, itls)
        ]
        ttft_violations = sum(value > max_request_ttft_ms for value in ttfts_ms)
        e2el_violations = sum(value > max_request_e2el_ms for value in e2els_ms)
        any_slo_violations = sum(
            ttft > max_request_ttft_ms or e2el > max_request_e2el_ms
            for ttft, e2el in zip(ttfts_ms, e2els_ms)
        )
        completed = int(payload["completed"])
        achieved_rps = float(payload["request_throughput"])
        raw_duration = payload.get("duration")
        duration_s = (
            float(raw_duration)
            if raw_duration is not None
            else completed / achieved_rps
        )
        recomputed_goodput_rps = (
            (completed - any_slo_violations) / duration_s
            if duration_s > 0
            else 0.0
        )

        raw_prefix_caching = payload.get("server_prefix_caching")
        if isinstance(raw_prefix_caching, bool):
            prefix_caching = raw_prefix_caching
        elif isinstance(raw_prefix_caching, str) and raw_prefix_caching.lower() in {
            "true",
            "false",
        }:
            prefix_caching = raw_prefix_caching.lower() == "true"
        else:
            prefix_caching = None

        def optional_int(key: str) -> int | None:
            raw_value = payload.get(key)
            if raw_value is None or str(raw_value).lower() in {"", "none", "unknown"}:
                return None
            return int(raw_value)

        def optional_float(key: str) -> float | None:
            raw_value = payload.get(key)
            if raw_value is None or str(raw_value).lower() in {"", "none", "unknown"}:
                return None
            return float(raw_value)

        return cls(
            source=path,
            offered_rps=float(payload["request_rate"]),
            completed=completed,
            failed=int(payload["failed"]),
            achieved_rps=achieved_rps,
            request_goodput_rps=recomputed_goodput_rps,
            p99_ttft_ms=float(payload["p99_ttft_ms"]),
            p99_e2el_ms=float(payload["p99_e2el_ms"]),
            ttft_violations=ttft_violations,
            e2el_violations=e2el_violations,
            any_slo_violations=any_slo_violations,
            seed=int(payload["seed"]) if "seed" in payload else None,
            server_prefix_caching=prefix_caching,
            server_max_num_batched_tokens=optional_int(
                "server_max_num_batched_tokens"
            ),
            server_max_num_seqs=optional_int("server_max_num_seqs"),
            workload_name=payload.get("workload_name"),
            input_tokens=optional_int("input_tokens"),
            output_tokens=optional_int("output_tokens"),
            configured_ttft_slo_ms=optional_float("ttft_slo_ms"),
            configured_e2el_slo_ms=optional_float("e2el_slo_ms"),
        )

    @property
    def request_compliance_rate(self) -> float:
        if self.completed == 0:
            return 0.0
        return (self.completed - self.any_slo_violations) / self.completed

    def window_meets_slo(
        self,
        max_p99_ttft_ms: float,
        max_p99_e2el_ms: float,
    ) -> bool:
        return (
            self.failed == 0
            and self.p99_ttft_ms <= max_p99_ttft_ms
            and self.p99_e2el_ms <= max_p99_e2el_ms
        )


def load_open_loop_runs(
    result_dir: Path,
    pattern: str = "poisson_*.json",
    max_request_ttft_ms: float = 100.0,
    max_request_e2el_ms: float = 400.0,
) -> list[OpenLoopRun]:
    """Load open-loop runs, preserving repetitions as separate evidence."""
    return sorted(
        (
            OpenLoopRun.from_json(
                path,
                max_request_ttft_ms=max_request_ttft_ms,
                max_request_e2el_ms=max_request_e2el_ms,
            )
            for path in result_dir.glob(pattern)
        ),
        key=lambda run: (run.offered_rps, run.source.name),
    )


def select_best_open_loop_run(
    runs: Iterable[OpenLoopRun],
    max_p99_ttft_ms: float,
    max_p99_e2el_ms: float,
) -> OpenLoopRun | None:
    """Maximize measured goodput among windows that satisfy the P99 SLO."""
    feasible = [
        run
        for run in runs
        if run.window_meets_slo(max_p99_ttft_ms, max_p99_e2el_ms)
    ]
    return max(
        feasible,
        key=lambda run: (run.request_goodput_rps, -run.offered_rps),
        default=None,
    )


def wilson_interval(
    successes: int,
    trials: int,
    z: float = 1.959963984540054,
) -> tuple[float, float]:
    """Return a Wilson score interval for a binomial success probability."""
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not 0 <= successes <= trials:
        raise ValueError("successes must be between zero and trials")

    proportion = successes / trials
    z_squared = z * z
    denominator = 1.0 + z_squared / trials
    center = (proportion + z_squared / (2.0 * trials)) / denominator
    radius = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / trials
            + z_squared / (4.0 * trials * trials)
        )
        / denominator
    )
    return max(0.0, center - radius), min(1.0, center + radius)


@dataclass(frozen=True)
class RateAggregate:
    """Repeated measurements summarized at one offered request rate."""

    offered_rps: float
    trials: int
    feasible_trials: int
    pass_rate: float
    pass_rate_ci95_low: float
    pass_rate_ci95_high: float
    mean_achieved_rps: float
    mean_goodput_rps: float
    min_goodput_rps: float
    mean_request_compliance_rate: float
    mean_p99_ttft_ms: float
    mean_p99_e2el_ms: float
    worst_p99_ttft_ms: float
    worst_p99_e2el_ms: float

    def empirically_safe(
        self,
        min_repetitions: int,
        required_pass_rate: float,
        max_p99_ttft_ms: float,
        max_p99_e2el_ms: float,
        ttft_safety_margin_ms: float = 0.0,
        e2el_safety_margin_ms: float = 0.0,
    ) -> bool:
        return (
            self.trials >= min_repetitions
            and self.pass_rate >= required_pass_rate
            and self.worst_p99_ttft_ms
            <= max_p99_ttft_ms - ttft_safety_margin_ms
            and self.worst_p99_e2el_ms
            <= max_p99_e2el_ms - e2el_safety_margin_ms
        )


def aggregate_by_rate(
    runs: Iterable[OpenLoopRun],
    max_p99_ttft_ms: float,
    max_p99_e2el_ms: float,
) -> list[RateAggregate]:
    """Group repetitions by offered rate and summarize worst-case tails."""
    grouped: dict[float, list[OpenLoopRun]] = {}
    for run in runs:
        grouped.setdefault(run.offered_rps, []).append(run)

    aggregates = []
    for offered_rps, repetitions in grouped.items():
        feasible_trials = sum(
            run.window_meets_slo(max_p99_ttft_ms, max_p99_e2el_ms)
            for run in repetitions
        )
        interval_low, interval_high = wilson_interval(
            feasible_trials, len(repetitions)
        )
        aggregates.append(
            RateAggregate(
                offered_rps=offered_rps,
                trials=len(repetitions),
                feasible_trials=feasible_trials,
                pass_rate=feasible_trials / len(repetitions),
                pass_rate_ci95_low=interval_low,
                pass_rate_ci95_high=interval_high,
                mean_achieved_rps=mean(run.achieved_rps for run in repetitions),
                mean_goodput_rps=mean(
                    run.request_goodput_rps for run in repetitions
                ),
                min_goodput_rps=min(
                    run.request_goodput_rps for run in repetitions
                ),
                mean_request_compliance_rate=mean(
                    run.request_compliance_rate for run in repetitions
                ),
                mean_p99_ttft_ms=mean(
                    run.p99_ttft_ms for run in repetitions
                ),
                mean_p99_e2el_ms=mean(
                    run.p99_e2el_ms for run in repetitions
                ),
                worst_p99_ttft_ms=max(
                    run.p99_ttft_ms for run in repetitions
                ),
                worst_p99_e2el_ms=max(
                    run.p99_e2el_ms for run in repetitions
                ),
            )
        )
    return sorted(aggregates, key=lambda aggregate: aggregate.offered_rps)


def select_empirically_safe_rate(
    aggregates: Iterable[RateAggregate],
    min_repetitions: int,
    required_pass_rate: float,
    max_p99_ttft_ms: float,
    max_p99_e2el_ms: float,
    ttft_safety_margin_ms: float = 0.0,
    e2el_safety_margin_ms: float = 0.0,
) -> RateAggregate | None:
    """Choose the highest rate satisfying a repeated-measurement policy."""
    feasible = [
        aggregate
        for aggregate in aggregates
        if aggregate.empirically_safe(
            min_repetitions=min_repetitions,
            required_pass_rate=required_pass_rate,
            max_p99_ttft_ms=max_p99_ttft_ms,
            max_p99_e2el_ms=max_p99_e2el_ms,
            ttft_safety_margin_ms=ttft_safety_margin_ms,
            e2el_safety_margin_ms=e2el_safety_margin_ms,
        )
    ]
    return max(feasible, key=lambda aggregate: aggregate.offered_rps, default=None)
