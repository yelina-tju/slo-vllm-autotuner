"""Rolling workload detection and safe serving-policy state machine."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ShapePrototype:
    name: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class RequestObservation:
    timestamp_s: float
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class SloLimit:
    ttft_ms: float
    e2el_ms: float


@dataclass(frozen=True)
class ClassWindowMetrics:
    completed: int
    failed: int
    p99_ttft_ms: float
    p99_e2el_ms: float
    violating_request_ids: tuple[int, ...] = ()
    successful_request_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ServingPolicy:
    name: str
    profile: str
    max_num_batched_tokens: int
    max_num_seqs: int
    scheduling_policy: str
    admission_limit_rps: float
    slo_limits: dict[str, SloLimit]

    def server_environment(self) -> dict[str, str]:
        return {
            "MAX_NUM_BATCHED_TOKENS": str(self.max_num_batched_tokens),
            "MAX_NUM_SEQS": str(self.max_num_seqs),
            "SCHEDULING_POLICY": self.scheduling_policy,
        }


@dataclass(frozen=True)
class PolicyBundle:
    profile: str
    primary_policy: str
    rollback_policy: str | None = None
    compatible_policies: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyCatalog:
    policies: dict[str, ServingPolicy]
    bundles: dict[str, PolicyBundle]

    def primary_for(self, profile: str) -> ServingPolicy:
        return self.policies[self.bundles[profile].primary_policy]

    def target_for(
        self, profile: str, current_policy: ServingPolicy
    ) -> ServingPolicy:
        """Prefer an evidence-backed target that reuses the running backend."""
        bundle = self.bundles[profile]
        alternatives = (
            bundle.primary_policy,
            *bundle.compatible_policies,
        )
        compatible = [
            self.policies[name]
            for name in alternatives
            if self.policies[name].server_environment()
            == current_policy.server_environment()
        ]
        if compatible:
            return max(
                compatible,
                key=lambda policy: (policy.admission_limit_rps, policy.name),
            )
        return self.policies[bundle.primary_policy]

    def rollback_for(self, profile: str) -> ServingPolicy | None:
        name = self.bundles[profile].rollback_policy
        return self.policies[name] if name is not None else None


@dataclass(frozen=True)
class ControllerConfig:
    rolling_window_seconds: float
    minimum_samples: int
    minimum_evaluation_interval_seconds: float
    switch_confirmation_windows: int
    switch_margin: float
    compatible_recovery_confirmation_windows: int
    compatible_recovery_switch_margin: float
    compatible_recovery_rollback_enabled: bool
    compatible_recovery_canary_admission_limits_rps: tuple[float, ...]
    compatible_recovery_canary_pass_windows: int
    max_profile_distance: float
    cooldown_seconds: float
    rollback_confirmation_windows: int
    rollback_cooldown_seconds: float
    minimum_slo_samples_per_class: int
    default_profile: str
    mixed_profile_name: str
    default_max_num_seqs: int
    shape_prototypes: tuple[ShapePrototype, ...]
    profile_distributions: dict[str, dict[str, float]]
    slo_class_mapping: dict[str, dict[str, str]]

    @classmethod
    def from_json(cls, path: Path) -> "ControllerConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        shapes = tuple(
            ShapePrototype(
                name=name,
                input_tokens=int(spec["input_tokens"]),
                output_tokens=int(spec["output_tokens"]),
            )
            for name, spec in payload["shape_prototypes"].items()
        )
        distributions = {
            profile: {name: float(weight) for name, weight in weights.items()}
            for profile, weights in payload["profile_distributions"].items()
        }
        slo_class_mapping = {
            profile: {shape: str(class_name) for shape, class_name in mapping.items()}
            for profile, mapping in payload["slo_class_mapping"].items()
        }
        for profile, weights in distributions.items():
            total = sum(weights.values())
            if not math.isclose(total, 1.0, abs_tol=1e-9):
                raise ValueError(f"{profile}: distribution must sum to one")
        canary_limits = tuple(
            float(value)
            for value in payload.get(
                "compatible_recovery_canary_admission_limits_rps", []
            )
        )
        if (
            any(not math.isfinite(value) or value <= 0 for value in canary_limits)
            or tuple(sorted(set(canary_limits))) != canary_limits
        ):
            raise ValueError(
                "compatible recovery canary limits must be finite, positive, "
                "strictly increasing and unique"
            )
        canary_pass_windows = int(
            payload.get("compatible_recovery_canary_pass_windows", 1)
        )
        if canary_pass_windows <= 0:
            raise ValueError("compatible recovery canary pass windows must be positive")
        return cls(
            rolling_window_seconds=float(payload["rolling_window_seconds"]),
            minimum_samples=int(payload["minimum_samples"]),
            minimum_evaluation_interval_seconds=float(
                payload["minimum_evaluation_interval_seconds"]
            ),
            switch_confirmation_windows=int(
                payload["switch_confirmation_windows"]
            ),
            switch_margin=float(payload["switch_margin"]),
            compatible_recovery_confirmation_windows=int(
                payload.get(
                    "compatible_recovery_confirmation_windows",
                    payload["switch_confirmation_windows"],
                )
            ),
            compatible_recovery_switch_margin=float(
                payload.get(
                    "compatible_recovery_switch_margin",
                    payload["switch_margin"],
                )
            ),
            compatible_recovery_rollback_enabled=bool(
                payload.get("compatible_recovery_rollback_enabled", False)
            ),
            compatible_recovery_canary_admission_limits_rps=canary_limits,
            compatible_recovery_canary_pass_windows=canary_pass_windows,
            max_profile_distance=float(payload["max_profile_distance"]),
            cooldown_seconds=float(payload["cooldown_seconds"]),
            rollback_confirmation_windows=int(
                payload["rollback_confirmation_windows"]
            ),
            rollback_cooldown_seconds=float(
                payload["rollback_cooldown_seconds"]
            ),
            minimum_slo_samples_per_class=int(
                payload["minimum_slo_samples_per_class"]
            ),
            default_profile=str(payload["default_profile"]),
            mixed_profile_name=str(payload["mixed_profile_name"]),
            default_max_num_seqs=int(payload["default_max_num_seqs"]),
            shape_prototypes=shapes,
            profile_distributions=distributions,
            slo_class_mapping=slo_class_mapping,
        )


@dataclass(frozen=True)
class DetectorSnapshot:
    timestamp_s: float
    sample_count: int
    estimated_rps: float
    distribution: dict[str, float]
    profile_distances: dict[str, float]
    best_profile: str | None
    best_distance: float | None
    status: str


class RollingWorkloadDetector:
    """Classify request shapes and compare a rolling mix with known profiles."""

    def __init__(
        self,
        window_seconds: float,
        minimum_samples: int,
        shape_prototypes: Sequence[ShapePrototype],
        profile_distributions: Mapping[str, Mapping[str, float]],
    ) -> None:
        if window_seconds <= 0 or minimum_samples <= 0:
            raise ValueError("window_seconds and minimum_samples must be positive")
        self.window_seconds = window_seconds
        self.minimum_samples = minimum_samples
        self.shape_prototypes = tuple(shape_prototypes)
        self.profile_distributions = {
            profile: dict(distribution)
            for profile, distribution in profile_distributions.items()
        }
        self._observations: deque[tuple[float, str]] = deque()
        self._last_timestamp_s: float | None = None

    def classify_shape(self, input_tokens: int, output_tokens: int) -> str:
        if input_tokens <= 0 or output_tokens <= 0:
            raise ValueError("token counts must be positive")

        def distance(prototype: ShapePrototype) -> float:
            return abs(math.log2(input_tokens / prototype.input_tokens)) + abs(
                math.log2(output_tokens / prototype.output_tokens)
            )

        return min(
            self.shape_prototypes,
            key=lambda prototype: (distance(prototype), prototype.name),
        ).name

    def observe(self, observation: RequestObservation) -> str:
        if (
            self._last_timestamp_s is not None
            and observation.timestamp_s < self._last_timestamp_s
        ):
            raise ValueError("request observations must be time ordered")
        shape = self.classify_shape(
            observation.input_tokens, observation.output_tokens
        )
        self._observations.append((observation.timestamp_s, shape))
        self._last_timestamp_s = observation.timestamp_s
        self._trim(observation.timestamp_s)
        return shape

    def snapshot(self, now_s: float) -> DetectorSnapshot:
        self._trim(now_s)
        counts = {prototype.name: 0 for prototype in self.shape_prototypes}
        for _, shape in self._observations:
            counts[shape] += 1
        sample_count = len(self._observations)
        distribution = {
            name: count / sample_count if sample_count else 0.0
            for name, count in counts.items()
        }
        estimated_rps = sample_count / self.window_seconds
        if sample_count < self.minimum_samples:
            return DetectorSnapshot(
                timestamp_s=now_s,
                sample_count=sample_count,
                estimated_rps=estimated_rps,
                distribution=distribution,
                profile_distances={},
                best_profile=None,
                best_distance=None,
                status="insufficient_samples",
            )

        distances = {
            profile: total_variation_distance(distribution, prototype)
            for profile, prototype in self.profile_distributions.items()
        }
        best_profile = min(distances, key=lambda name: (distances[name], name))
        return DetectorSnapshot(
            timestamp_s=now_s,
            sample_count=sample_count,
            estimated_rps=estimated_rps,
            distribution=distribution,
            profile_distances=distances,
            best_profile=best_profile,
            best_distance=distances[best_profile],
            status="ready",
        )

    def _trim(self, now_s: float) -> None:
        cutoff = now_s - self.window_seconds
        while self._observations and self._observations[0][0] < cutoff:
            self._observations.popleft()


def total_variation_distance(
    observed: Mapping[str, float],
    expected: Mapping[str, float],
) -> float:
    names = set(observed) | set(expected)
    return 0.5 * sum(
        abs(float(observed.get(name, 0.0)) - float(expected.get(name, 0.0)))
        for name in names
    )


@dataclass(frozen=True)
class SloEvaluation:
    status: str
    reasons: tuple[str, ...]


def evaluate_policy_slo(
    policy: ServingPolicy,
    metrics: Mapping[str, ClassWindowMetrics],
    minimum_samples_per_class: int,
) -> SloEvaluation:
    violations: list[str] = []
    insufficient: list[str] = []
    for class_name, limit in policy.slo_limits.items():
        observed = metrics.get(class_name)
        if observed is None:
            insufficient.append(f"{class_name}: missing metrics")
            continue
        if observed.failed > 0:
            violations.append(f"{class_name}: {observed.failed} failed requests")
        if observed.completed < minimum_samples_per_class:
            insufficient.append(
                f"{class_name}: only {observed.completed} completed requests"
            )
            continue
        if observed.p99_ttft_ms > limit.ttft_ms:
            violations.append(
                f"{class_name}: P99 TTFT {observed.p99_ttft_ms:.2f} > "
                f"{limit.ttft_ms:.2f} ms"
            )
        if observed.p99_e2el_ms > limit.e2el_ms:
            violations.append(
                f"{class_name}: P99 E2E {observed.p99_e2el_ms:.2f} > "
                f"{limit.e2el_ms:.2f} ms"
            )
    if violations:
        return SloEvaluation("violation", tuple(violations))
    if insufficient:
        return SloEvaluation("insufficient_samples", tuple(insufficient))
    return SloEvaluation("pass", ())


@dataclass(frozen=True)
class ControlDecision:
    timestamp_s: float
    action: str
    from_policy: str
    to_policy: str
    active_profile: str
    reason: str
    pending_profile: str | None
    pending_count: int
    cooldown_until_s: float
    admission_limit_rps: float
    server_environment: dict[str, str]
    requires_server_restart: bool
    detector: DetectorSnapshot | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AdaptiveServingController:
    """State machine with confirmation, hysteresis, cooldown and rollback."""

    def __init__(
        self,
        config: ControllerConfig,
        catalog: PolicyCatalog,
        detector: RollingWorkloadDetector,
    ) -> None:
        if config.default_profile not in catalog.bundles:
            raise ValueError("default profile is missing from policy catalog")
        self.config = config
        self.catalog = self._with_canary_policies(catalog)
        self.detector = detector
        self.active_profile = config.default_profile
        self.active_policy_name = catalog.primary_for(config.default_profile).name
        self.pending_profile: str | None = None
        self.pending_count = 0
        self.cooldown_until_s = 0.0
        self.last_evaluation_s: float | None = None
        self.consecutive_slo_violations = 0
        self.seen_slo_violation_request_ids: set[int] = set()
        self.recovery_rollback_policy_name: str | None = None
        self.recovery_rollback_profile: str | None = None
        self.capacity_increase_block_until_s = 0.0
        self.canary_target_policy_name: str | None = None
        self.canary_pass_count = 0
        self.seen_canary_pass_request_ids: set[int] = set()

    @property
    def active_policy(self) -> ServingPolicy:
        return self.catalog.policies[self.active_policy_name]

    def observe_request(self, observation: RequestObservation) -> str:
        return self.detector.observe(observation)

    def tick(self, now_s: float) -> ControlDecision:
        current = self.active_policy_name
        if (
            self.last_evaluation_s is not None
            and now_s - self.last_evaluation_s
            < self.config.minimum_evaluation_interval_seconds
        ):
            return self._decision(
                now_s,
                "hold",
                current,
                "evaluation interval has not elapsed",
            )
        self.last_evaluation_s = now_s
        snapshot = self.detector.snapshot(now_s)
        if snapshot.status != "ready":
            self._clear_pending()
            return self._decision(
                now_s,
                "hold",
                current,
                "insufficient workload samples",
                snapshot,
            )
        candidate = self._candidate_profile(snapshot)
        if candidate is None:
            self._clear_pending()
            return self._decision(
                now_s,
                "hold",
                current,
                "active profile retained by distance/hysteresis",
                snapshot,
            )
        full_target = self.catalog.target_for(candidate, self.active_policy)
        requires_restart = (
            self.active_policy.server_environment()
            != full_target.server_environment()
        )
        compatible_recovery = (
            not requires_restart
            and full_target.admission_limit_rps
            > self.active_policy.admission_limit_rps
        )
        if (
            compatible_recovery
            and now_s < self.capacity_increase_block_until_s
        ):
            self._clear_pending()
            return self._decision(
                now_s,
                "hold",
                current,
                "capacity-increase recovery cooldown is active",
                snapshot,
            )
        target = (
            self._next_canary_policy(full_target, self.active_policy.admission_limit_rps)
            if compatible_recovery
            else full_target
        )
        required_margin = (
            self.config.compatible_recovery_switch_margin
            if compatible_recovery
            else self.config.switch_margin
        )
        active_distance = snapshot.profile_distances.get(self.active_profile, 1.0)
        improvement = active_distance - (snapshot.best_distance or 0.0)
        if improvement < required_margin:
            self._clear_pending()
            return self._decision(
                now_s,
                "hold",
                current,
                "active profile retained by distance/hysteresis",
                snapshot,
            )
        if now_s < self.cooldown_until_s and requires_restart:
            self._clear_pending()
            return self._decision(
                now_s,
                "hold",
                current,
                "restart cooldown is active",
                snapshot,
            )
        if candidate == self.pending_profile:
            self.pending_count += 1
        else:
            self.pending_profile = candidate
            self.pending_count = 1
        required_confirmations = (
            self.config.compatible_recovery_confirmation_windows
            if compatible_recovery
            else self.config.switch_confirmation_windows
        )
        if self.pending_count < required_confirmations:
            return self._decision(
                now_s,
                "hold",
                current,
                f"candidate {candidate} awaiting confirmation",
                snapshot,
            )

        previous = self.active_policy_name
        previous_profile = self.active_profile
        self.active_profile = candidate
        self.active_policy_name = target.name
        if (
            compatible_recovery
            and self.config.compatible_recovery_rollback_enabled
        ):
            self.recovery_rollback_policy_name = previous
            self.recovery_rollback_profile = previous_profile
        else:
            self._clear_recovery_rollback()
        if compatible_recovery and target.name != full_target.name:
            self.canary_target_policy_name = full_target.name
            self._reset_canary_pass_evidence()
        else:
            self._clear_canary_progress()
        if requires_restart:
            self.cooldown_until_s = now_s + self.config.cooldown_seconds
        self._reset_slo_evidence()
        self._clear_pending()
        return self._decision(
            now_s,
            "switch",
            previous,
            f"confirmed workload profile {candidate}",
            snapshot,
        )

    def report_slo_window(
        self,
        now_s: float,
        metrics: Mapping[str, ClassWindowMetrics],
    ) -> ControlDecision:
        current = self.active_policy
        evaluation = evaluate_policy_slo(
            current,
            metrics,
            self.config.minimum_slo_samples_per_class,
        )
        if evaluation.status == "pass":
            self._reset_slo_evidence()
            canary_decision = self._report_canary_pass(now_s, metrics)
            if canary_decision is not None:
                return canary_decision
            return self._decision(
                now_s,
                "hold",
                current.name,
                "SLO window pass",
            )
        if evaluation.status != "violation":
            self._reset_slo_evidence()
            self._reset_canary_pass_evidence()
            return self._decision(
                now_s,
                "hold",
                current.name,
                f"SLO window {evaluation.status}",
            )

        self._reset_canary_pass_evidence()
        reason = "; ".join(evaluation.reasons)
        evidence = {
            request_id
            for observed in metrics.values()
            for request_id in observed.violating_request_ids
        }
        new_evidence = evidence - self.seen_slo_violation_request_ids
        if not new_evidence:
            return self._decision(
                now_s,
                "hold",
                current.name,
                "SLO violation has no new violating requests: " + reason,
            )
        self.seen_slo_violation_request_ids.update(new_evidence)
        self.consecutive_slo_violations += 1
        if (
            self.consecutive_slo_violations
            < self.config.rollback_confirmation_windows
        ):
            return self._decision(
                now_s,
                "hold",
                current.name,
                "SLO violation awaiting rollback confirmation: " + reason,
            )

        recovery_rollback = (
            self.catalog.policies.get(self.recovery_rollback_policy_name)
            if self.config.compatible_recovery_rollback_enabled
            and self.recovery_rollback_policy_name is not None
            else None
        )
        rollback = recovery_rollback or self.catalog.rollback_for(self.active_profile)
        if rollback is None or rollback.name == current.name:
            self._clear_canary_progress()
            return self._decision(
                now_s,
                "alert",
                current.name,
                "confirmed SLO violation but no distinct rollback exists: "
                + reason,
            )

        previous = current.name
        if recovery_rollback is not None:
            assert self.recovery_rollback_profile is not None
            self.active_profile = self.recovery_rollback_profile
        self.active_policy_name = rollback.name
        self.cooldown_until_s = now_s + self.config.rollback_cooldown_seconds
        if recovery_rollback is not None:
            self.capacity_increase_block_until_s = (
                now_s + self.config.rollback_cooldown_seconds
            )
        self._clear_recovery_rollback()
        self._clear_canary_progress()
        self._reset_slo_evidence()
        self._clear_pending()
        return self._decision(
            now_s,
            "rollback",
            previous,
            "confirmed SLO violation: " + reason,
        )

    def state_dict(self) -> dict[str, Any]:
        return {
            "active_profile": self.active_profile,
            "active_policy": self.active_policy_name,
            "pending_profile": self.pending_profile,
            "pending_count": self.pending_count,
            "cooldown_until_s": self.cooldown_until_s,
            "last_evaluation_s": self.last_evaluation_s,
            "consecutive_slo_violations": self.consecutive_slo_violations,
            "seen_slo_violation_request_ids": sorted(
                self.seen_slo_violation_request_ids
            ),
            "recovery_rollback_policy": self.recovery_rollback_policy_name,
            "recovery_rollback_profile": self.recovery_rollback_profile,
            "capacity_increase_block_until_s": self.capacity_increase_block_until_s,
            "canary_target_policy": self.canary_target_policy_name,
            "canary_pass_count": self.canary_pass_count,
            "seen_canary_pass_request_ids": sorted(
                self.seen_canary_pass_request_ids
            ),
            "admission_limit_rps": self.active_policy.admission_limit_rps,
            "server_environment": self.active_policy.server_environment(),
        }

    def force_active_policy(
        self,
        policy_name: str,
        now_s: float,
        cooldown_seconds: float,
    ) -> None:
        """Restore controller state after an execution-layer failure."""
        policy = self.catalog.policies[policy_name]
        self.active_profile = policy.profile
        self.active_policy_name = policy.name
        self.cooldown_until_s = now_s + cooldown_seconds
        self._clear_recovery_rollback()
        self._clear_canary_progress()
        self._reset_slo_evidence()
        self._clear_pending()

    def restore_after_execution_failure(
        self,
        decision: ControlDecision,
        now_s: float,
        cooldown_seconds: float,
    ) -> None:
        """Restore the source while preserving a failed admission rollback target."""
        self.force_active_policy(decision.from_policy, now_s, cooldown_seconds)
        self.capacity_increase_block_until_s = now_s + cooldown_seconds
        source = self.catalog.policies[decision.from_policy]
        target = self.catalog.policies[decision.to_policy]
        retryable_recovery_rollback = (
            decision.action == "rollback"
            and source.server_environment() == target.server_environment()
            and target.admission_limit_rps < source.admission_limit_rps
        )
        if retryable_recovery_rollback:
            self.recovery_rollback_policy_name = target.name
            self.recovery_rollback_profile = target.profile

    def force_profile_decision(
        self,
        profile: str,
        now_s: float,
        reason: str = "externally scheduled profile transition",
    ) -> ControlDecision:
        """Create a switch decision without detector confirmation or cooldown.

        This is intentionally separate from ``tick`` and is used by controlled
        oracle experiments that know the true workload phase boundary.
        """
        if profile not in self.catalog.bundles:
            raise KeyError(f"unknown profile: {profile}")
        previous = self.active_policy_name
        target = self.catalog.target_for(profile, self.active_policy)
        self.active_profile = profile
        self.active_policy_name = target.name
        self._clear_recovery_rollback()
        self._clear_canary_progress()
        self._reset_slo_evidence()
        self._clear_pending()
        return self._decision(now_s, "switch", previous, reason)

    def _reset_slo_evidence(self) -> None:
        self.consecutive_slo_violations = 0
        self.seen_slo_violation_request_ids.clear()

    def _candidate_profile(self, snapshot: DetectorSnapshot) -> str | None:
        candidate = snapshot.best_profile
        if candidate is None or candidate == self.active_profile:
            return None
        if candidate not in self.catalog.bundles:
            return None
        assert snapshot.best_distance is not None
        if snapshot.best_distance > self.config.max_profile_distance:
            return None
        return candidate

    def _clear_pending(self) -> None:
        self.pending_profile = None
        self.pending_count = 0

    def _clear_recovery_rollback(self) -> None:
        self.recovery_rollback_policy_name = None
        self.recovery_rollback_profile = None

    def _reset_canary_pass_evidence(self) -> None:
        self.canary_pass_count = 0
        self.seen_canary_pass_request_ids.clear()

    def _clear_canary_progress(self) -> None:
        self.canary_target_policy_name = None
        self._reset_canary_pass_evidence()

    def _report_canary_pass(
        self,
        now_s: float,
        metrics: Mapping[str, ClassWindowMetrics],
    ) -> ControlDecision | None:
        if self.canary_target_policy_name is None:
            self._reset_canary_pass_evidence()
            return None
        current = self.active_policy
        if self.pending_profile is not None:
            self._reset_canary_pass_evidence()
            return self._decision(
                now_s,
                "hold",
                current.name,
                "canary promotion paused by a pending workload change",
            )
        evidence = {
            request_id
            for observed in metrics.values()
            for request_id in observed.successful_request_ids
        }
        new_evidence = evidence - self.seen_canary_pass_request_ids
        if not new_evidence:
            return self._decision(
                now_s,
                "hold",
                current.name,
                "canary SLO pass has no new successful requests",
            )
        self.seen_canary_pass_request_ids.update(new_evidence)
        self.canary_pass_count += 1
        if (
            self.canary_pass_count
            < self.config.compatible_recovery_canary_pass_windows
        ):
            return self._decision(
                now_s,
                "hold",
                current.name,
                "canary SLO pass awaiting promotion confirmation",
            )

        full_target = self.catalog.policies[self.canary_target_policy_name]
        target = self._next_canary_policy(
            full_target,
            current.admission_limit_rps,
        )
        previous = current.name
        previous_profile = self.active_profile
        self.active_policy_name = target.name
        if self.config.compatible_recovery_rollback_enabled:
            self.recovery_rollback_policy_name = previous
            self.recovery_rollback_profile = previous_profile
        if target.name == full_target.name:
            self._clear_canary_progress()
        else:
            self._reset_canary_pass_evidence()
        self._reset_slo_evidence()
        return self._decision(
            now_s,
            "switch",
            previous,
            f"canary SLO pass promoted admission to {target.admission_limit_rps:g} req/s",
        )

    def _next_canary_policy(
        self,
        full_target: ServingPolicy,
        current_admission_limit_rps: float,
    ) -> ServingPolicy:
        for limit in self.config.compatible_recovery_canary_admission_limits_rps:
            if current_admission_limit_rps < limit < full_target.admission_limit_rps:
                return self.catalog.policies[
                    self._canary_policy_name(full_target.name, limit)
                ]
        return full_target

    def _with_canary_policies(self, catalog: PolicyCatalog) -> PolicyCatalog:
        policies = dict(catalog.policies)
        for policy in tuple(catalog.policies.values()):
            for limit in self.config.compatible_recovery_canary_admission_limits_rps:
                if limit >= policy.admission_limit_rps:
                    continue
                name = self._canary_policy_name(policy.name, limit)
                policies[name] = replace(
                    policy,
                    name=name,
                    admission_limit_rps=limit,
                )
        return PolicyCatalog(policies=policies, bundles=catalog.bundles)

    @staticmethod
    def _canary_policy_name(policy_name: str, limit: float) -> str:
        return f"{policy_name}:canary-{limit:g}rps"

    def _decision(
        self,
        now_s: float,
        action: str,
        from_policy: str,
        reason: str,
        detector: DetectorSnapshot | None = None,
    ) -> ControlDecision:
        target = self.active_policy
        source = self.catalog.policies[from_policy]
        return ControlDecision(
            timestamp_s=now_s,
            action=action,
            from_policy=from_policy,
            to_policy=self.active_policy_name,
            active_profile=self.active_profile,
            reason=reason,
            pending_profile=self.pending_profile,
            pending_count=self.pending_count,
            cooldown_until_s=self.cooldown_until_s,
            admission_limit_rps=target.admission_limit_rps,
            server_environment=target.server_environment(),
            requires_server_restart=(
                source.server_environment() != target.server_environment()
            ),
            detector=detector,
        )


def load_policy_catalog(
    workload_policy_path: Path,
    workload_profiles_path: Path,
    mixed_policy_path: Path,
    mixed_profile_name: str,
    default_max_num_seqs: int = 256,
) -> PolicyCatalog:
    """Build executable policies from the experiment-generated JSON files."""
    workload_policy = json.loads(workload_policy_path.read_text(encoding="utf-8"))
    workload_profiles = json.loads(
        workload_profiles_path.read_text(encoding="utf-8")
    )
    profile_specs = {
        item["name"]: item for item in workload_profiles["profiles"]
    }
    policies: dict[str, ServingPolicy] = {}
    bundles: dict[str, PolicyBundle] = {}

    for entry in workload_policy["policies"]:
        if entry.get("status") != "ready":
            continue
        profile = entry["workload"]
        spec = profile_specs[profile]
        max_tokens, max_seqs = parse_candidate_name(entry["selected_candidate"])
        policy_name = f"{profile}:{entry['selected_candidate']}"
        policies[policy_name] = ServingPolicy(
            name=policy_name,
            profile=profile,
            max_num_batched_tokens=max_tokens,
            max_num_seqs=max_seqs,
            scheduling_policy="fcfs",
            admission_limit_rps=float(entry["robust_capacity_rps"]),
            slo_limits={
                profile: SloLimit(
                    ttft_ms=float(spec["ttft_slo_ms"]),
                    e2el_ms=float(spec["e2el_slo_ms"]),
                )
            },
        )
        compatible_policy_names = []
        for compatible in entry.get("compatible_candidates", []):
            if compatible.get("status") != "ready":
                continue
            compatible_candidate = str(compatible["candidate"])
            compatible_name = f"{profile}:{compatible_candidate}"
            if compatible_name == policy_name:
                continue
            compatible_tokens, compatible_seqs = parse_candidate_name(
                compatible_candidate
            )
            policies[compatible_name] = ServingPolicy(
                name=compatible_name,
                profile=profile,
                max_num_batched_tokens=compatible_tokens,
                max_num_seqs=compatible_seqs,
                scheduling_policy="fcfs",
                admission_limit_rps=float(compatible["robust_capacity_rps"]),
                slo_limits={
                    profile: SloLimit(
                        ttft_ms=float(spec["ttft_slo_ms"]),
                        e2el_ms=float(spec["e2el_slo_ms"]),
                    )
                },
            )
            compatible_policy_names.append(compatible_name)
        bundles[profile] = PolicyBundle(
            profile,
            policy_name,
            compatible_policies=tuple(compatible_policy_names),
        )

    mixed = json.loads(mixed_policy_path.read_text(encoding="utf-8"))
    if mixed.get("status") == "ready":
        slo_limits = {
            item["name"]: SloLimit(
                ttft_ms=float(item["ttft_slo_ms"]),
                e2el_ms=float(item["e2el_slo_ms"]),
            )
            for item in mixed["class_slos"]
        }

        def add_mixed_policy(kind: str) -> str | None:
            entry = mixed.get(kind)
            if entry is None:
                return None
            name = f"{mixed_profile_name}:{kind}:{entry['candidate']}"
            policies[name] = ServingPolicy(
                name=name,
                profile=mixed_profile_name,
                max_num_batched_tokens=int(entry["max_num_batched_tokens"]),
                max_num_seqs=default_max_num_seqs,
                scheduling_policy=str(entry["scheduling_policy"]),
                admission_limit_rps=float(entry["admission_limit_rps"]),
                slo_limits=dict(slo_limits),
            )
            return name

        primary = add_mixed_policy("selected")
        rollback = add_mixed_policy("rollback")
        if primary is not None:
            bundles[mixed_profile_name] = PolicyBundle(
                mixed_profile_name, primary, rollback
            )

    return PolicyCatalog(policies=policies, bundles=bundles)


def parse_candidate_name(candidate: str) -> tuple[int, int]:
    match = re.fullmatch(r"mbt(?P<mbt>\d+)-seq(?P<seq>\d+)", candidate)
    if match is None:
        raise ValueError(f"unsupported candidate name: {candidate}")
    return int(match.group("mbt")), int(match.group("seq"))
