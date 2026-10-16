"""Evidence-aware candidate evaluation for scheduler configuration search."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .open_loop import (
    OpenLoopRun,
    RateAggregate,
    aggregate_by_rate,
    select_empirically_safe_rate,
)


@dataclass(frozen=True)
class CandidateSpec:
    """One vLLM scheduler configuration and the files that measure it."""

    name: str
    max_num_batched_tokens: int
    max_num_seqs: int
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class CandidateEvaluation:
    """Capacity evidence collected for one scheduler candidate."""

    candidate: CandidateSpec
    rates: tuple[RateAggregate, ...]
    robust_capacity_rps: float | None
    observed_capacity_rps: float | None

    def aggregate_at(self, offered_rps: float) -> RateAggregate:
        for aggregate in self.rates:
            if aggregate.offered_rps == offered_rps:
                return aggregate
        raise KeyError(offered_rps)


def classify_rate(
    aggregate: RateAggregate,
    *,
    min_repetitions: int,
    required_pass_rate: float,
    max_p99_ttft_ms: float,
    max_p99_e2el_ms: float,
    ttft_safety_margin_ms: float = 0.0,
    e2el_safety_margin_ms: float = 0.0,
) -> str:
    """Label evidence without turning a single pass into a safety claim."""
    if aggregate.empirically_safe(
        min_repetitions=min_repetitions,
        required_pass_rate=required_pass_rate,
        max_p99_ttft_ms=max_p99_ttft_ms,
        max_p99_e2el_ms=max_p99_e2el_ms,
        ttft_safety_margin_ms=ttft_safety_margin_ms,
        e2el_safety_margin_ms=e2el_safety_margin_ms,
    ):
        return "robust_feasible"
    if aggregate.feasible_trials == aggregate.trials:
        return "observed_feasible_needs_repetition"
    if aggregate.feasible_trials == 0:
        return "observed_infeasible"
    return "unstable"


def evaluate_candidate_runs(
    candidate: CandidateSpec,
    runs: Iterable[OpenLoopRun],
    *,
    min_repetitions: int,
    required_pass_rate: float,
    max_p99_ttft_ms: float,
    max_p99_e2el_ms: float,
    ttft_safety_margin_ms: float = 0.0,
    e2el_safety_margin_ms: float = 0.0,
) -> CandidateEvaluation:
    """Estimate robust and provisional capacity from completed trials."""
    aggregates = aggregate_by_rate(
        runs,
        max_p99_ttft_ms=max_p99_ttft_ms,
        max_p99_e2el_ms=max_p99_e2el_ms,
    )
    robust = select_empirically_safe_rate(
        aggregates,
        min_repetitions=min_repetitions,
        required_pass_rate=required_pass_rate,
        max_p99_ttft_ms=max_p99_ttft_ms,
        max_p99_e2el_ms=max_p99_e2el_ms,
        ttft_safety_margin_ms=ttft_safety_margin_ms,
        e2el_safety_margin_ms=e2el_safety_margin_ms,
    )
    observed_rates = [
        aggregate.offered_rps
        for aggregate in aggregates
        if aggregate.feasible_trials == aggregate.trials
    ]
    return CandidateEvaluation(
        candidate=candidate,
        rates=tuple(aggregates),
        robust_capacity_rps=robust.offered_rps if robust else None,
        observed_capacity_rps=max(observed_rates, default=None),
    )


def load_candidate_runs(
    result_dir: Path,
    candidate: CandidateSpec,
    *,
    max_request_ttft_ms: float,
    max_request_e2el_ms: float,
) -> list[OpenLoopRun]:
    """Load and validate all unique files assigned to a candidate."""
    paths = sorted(
        {
            path
            for pattern in candidate.patterns
            for path in result_dir.glob(pattern)
        }
    )
    runs = [
        OpenLoopRun.from_json(
            path,
            max_request_ttft_ms=max_request_ttft_ms,
            max_request_e2el_ms=max_request_e2el_ms,
        )
        for path in paths
    ]
    for run in runs:
        if (
            run.server_max_num_batched_tokens is not None
            and run.server_max_num_batched_tokens
            != candidate.max_num_batched_tokens
        ):
            raise ValueError(
                f"{run.source}: max_num_batched_tokens metadata does not "
                f"match candidate {candidate.name}"
            )
        if (
            run.server_max_num_seqs is not None
            and run.server_max_num_seqs != candidate.max_num_seqs
        ):
            raise ValueError(
                f"{run.source}: max_num_seqs metadata does not match "
                f"candidate {candidate.name}"
            )
    return runs


def select_candidate(
    evaluations: Iterable[CandidateEvaluation],
) -> tuple[CandidateEvaluation | None, bool]:
    """Select by capacity, then E2E headroom and goodput.

    The boolean result is true only when the selected capacity is backed by the
    configured repeated-measurement safety policy.
    """
    evaluations = list(evaluations)
    robust = [
        evaluation
        for evaluation in evaluations
        if evaluation.robust_capacity_rps is not None
    ]
    if robust:
        return max(robust, key=lambda item: _selection_key(item, robust=True)), True

    provisional = [
        evaluation
        for evaluation in evaluations
        if evaluation.observed_capacity_rps is not None
    ]
    if not provisional:
        return None, False
    return (
        max(
            provisional,
            key=lambda item: _selection_key(item, robust=False),
        ),
        False,
    )


def _selection_key(
    evaluation: CandidateEvaluation,
    *,
    robust: bool,
) -> tuple[float, float, float]:
    capacity = (
        evaluation.robust_capacity_rps
        if robust
        else evaluation.observed_capacity_rps
    )
    assert capacity is not None
    aggregate = evaluation.aggregate_at(capacity)
    return (
        capacity,
        -aggregate.worst_p99_e2el_ms,
        aggregate.mean_goodput_rps,
    )
