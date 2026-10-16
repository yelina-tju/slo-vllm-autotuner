"""Evidence aggregation and policy selection for mixed-class workloads."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Sequence

from .mixed import RequestClass, summarize_records
from .open_loop import wilson_interval


@dataclass(frozen=True)
class MixedCandidateSpec:
    name: str
    max_num_batched_tokens: int
    scheduling_policy: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class MixedRun:
    source: Path
    offered_rps: float
    seed: int
    duration_s: float
    request_throughput: float
    request_goodput: float
    all_classes_meet_slo: bool
    classes: dict[str, dict[str, Any]]

    @classmethod
    def from_json(
        cls,
        path: Path,
        request_classes: Sequence[RequestClass],
    ) -> "MixedRun":
        payload = json.loads(path.read_text(encoding="utf-8"))
        duration_s = float(payload["duration"])
        summary = summarize_records(
            payload["requests"], request_classes, duration_s
        )
        return cls(
            source=path,
            offered_rps=float(payload["request_rate"]),
            seed=int(payload["seed"]),
            duration_s=duration_s,
            request_throughput=float(summary["request_throughput"]),
            request_goodput=float(summary["request_goodput"]),
            all_classes_meet_slo=bool(summary["all_classes_meet_slo"]),
            classes=summary["classes"],
        )


@dataclass(frozen=True)
class MixedRateAggregate:
    offered_rps: float
    trials: int
    feasible_trials: int
    pass_rate: float
    pass_rate_ci95_low: float
    pass_rate_ci95_high: float
    mean_throughput_rps: float
    mean_goodput_rps: float
    min_goodput_rps: float
    worst_p99_ttft_ms: dict[str, float]
    worst_p99_e2el_ms: dict[str, float]

    def robustly_feasible(
        self,
        min_repetitions: int,
        required_pass_rate: float,
    ) -> bool:
        return (
            self.trials >= min_repetitions
            and self.pass_rate >= required_pass_rate
        )


@dataclass(frozen=True)
class MixedCandidateEvaluation:
    candidate: MixedCandidateSpec
    rates: tuple[MixedRateAggregate, ...]
    robust_capacity_rps: float | None

    def aggregate_at(self, offered_rps: float) -> MixedRateAggregate:
        for aggregate in self.rates:
            if aggregate.offered_rps == offered_rps:
                return aggregate
        raise KeyError(offered_rps)


def aggregate_mixed_runs(
    runs: Iterable[MixedRun],
    class_names: Sequence[str],
) -> list[MixedRateAggregate]:
    grouped: dict[float, list[MixedRun]] = {}
    seen_trials: set[tuple[float, int]] = set()
    for run in runs:
        trial_key = (run.offered_rps, run.seed)
        if trial_key in seen_trials:
            raise ValueError(
                f"duplicate trial at rate={run.offered_rps}, seed={run.seed}"
            )
        seen_trials.add(trial_key)
        grouped.setdefault(run.offered_rps, []).append(run)

    aggregates = []
    for offered_rps, repetitions in grouped.items():
        feasible_trials = sum(run.all_classes_meet_slo for run in repetitions)
        ci_low, ci_high = wilson_interval(feasible_trials, len(repetitions))
        aggregates.append(
            MixedRateAggregate(
                offered_rps=offered_rps,
                trials=len(repetitions),
                feasible_trials=feasible_trials,
                pass_rate=feasible_trials / len(repetitions),
                pass_rate_ci95_low=ci_low,
                pass_rate_ci95_high=ci_high,
                mean_throughput_rps=mean(
                    run.request_throughput for run in repetitions
                ),
                mean_goodput_rps=mean(run.request_goodput for run in repetitions),
                min_goodput_rps=min(run.request_goodput for run in repetitions),
                worst_p99_ttft_ms={
                    name: max(
                        float(run.classes[name]["p99_ttft_ms"])
                        for run in repetitions
                    )
                    for name in class_names
                },
                worst_p99_e2el_ms={
                    name: max(
                        float(run.classes[name]["p99_e2el_ms"])
                        for run in repetitions
                    )
                    for name in class_names
                },
            )
        )
    return sorted(aggregates, key=lambda item: item.offered_rps)


def evaluate_mixed_candidate(
    candidate: MixedCandidateSpec,
    runs: Iterable[MixedRun],
    request_classes: Sequence[RequestClass],
    min_repetitions: int,
    required_pass_rate: float,
) -> MixedCandidateEvaluation:
    rates = aggregate_mixed_runs(
        runs, [request_class.name for request_class in request_classes]
    )
    robust_rates = [
        aggregate.offered_rps
        for aggregate in rates
        if aggregate.robustly_feasible(min_repetitions, required_pass_rate)
    ]
    return MixedCandidateEvaluation(
        candidate=candidate,
        rates=tuple(rates),
        robust_capacity_rps=max(robust_rates, default=None),
    )


def select_mixed_candidate(
    evaluations: Iterable[MixedCandidateEvaluation],
    request_classes: Sequence[RequestClass],
) -> MixedCandidateEvaluation | None:
    """Select capacity first, then worst normalized E2E headroom and goodput."""
    class_slos = {
        request_class.name: request_class.e2el_slo_ms
        for request_class in request_classes
    }
    feasible = [
        evaluation
        for evaluation in evaluations
        if evaluation.robust_capacity_rps is not None
    ]
    if not feasible:
        return None

    def selection_key(
        evaluation: MixedCandidateEvaluation,
    ) -> tuple[float, float, float]:
        capacity = evaluation.robust_capacity_rps
        assert capacity is not None
        aggregate = evaluation.aggregate_at(capacity)
        worst_normalized_e2el = max(
            aggregate.worst_p99_e2el_ms[name] / class_slos[name]
            for name in class_slos
        )
        return capacity, -worst_normalized_e2el, aggregate.mean_goodput_rps

    return max(feasible, key=selection_key)


def load_candidate_runs(
    result_dir: Path,
    candidate: MixedCandidateSpec,
    request_classes: Sequence[RequestClass],
) -> list[MixedRun]:
    paths = sorted(
        {
            path
            for pattern in candidate.patterns
            for path in result_dir.glob(pattern)
        }
    )
    runs = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        server = payload.get("server", {})
        raw_mbt = server.get("max_num_batched_tokens")
        if raw_mbt not in {None, "unknown"} and int(raw_mbt) != (
            candidate.max_num_batched_tokens
        ):
            raise ValueError(f"{path}: max_num_batched_tokens mismatch")
        raw_policy = server.get("scheduling_policy")
        if raw_policy not in {None, "unknown", candidate.scheduling_policy}:
            raise ValueError(f"{path}: scheduling_policy mismatch")
        runs.append(MixedRun.from_json(path, request_classes))
    return runs
