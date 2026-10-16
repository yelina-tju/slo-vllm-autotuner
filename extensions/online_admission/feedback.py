"""Pure feedback prototype: propose first, acknowledge applied changes later."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Config:
    minimum: float = 1.0
    maximum: float = 12.0
    initial: float = 3.0
    additive_step: float = 1.0
    decrease_factor: float = 0.7
    grow_below: float = 0.8
    demand_fraction: float = 0.9
    minimum_samples: int = 30
    confirmations: int = 2
    settle_seconds: float = 20.0

    def __post_init__(self):
        if not all(math.isfinite(v) for v in vars(self).values()):
            raise ValueError('configuration must be finite')
        if not (0 < self.minimum <= self.initial <= self.maximum
                and self.additive_step > 0 and 0 < self.decrease_factor < 1
                and 0 < self.grow_below < 1 and 0 < self.demand_fraction <= 1
                and self.settle_seconds >= 0):
            raise ValueError('invalid feedback limits')
        if any(type(v) is not int or v < 1 for v in (self.minimum_samples, self.confirmations)):
            raise ValueError('sample/confirmation counts must be positive integers')


@dataclass(frozen=True)
class ClassEvidence:
    completed: int
    failed: int
    # Ratios to frozen class-specific SLOs; None means unobservable.
    ttft_ratio: float | None
    e2e_ratio: float | None

    def __post_init__(self):
        if any(type(v) is not int or v < 0 for v in (self.completed, self.failed)):
            raise ValueError('invalid outcome counts')
        for value in (self.ttft_ratio, self.e2e_ratio):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError('invalid latency ratio')

    @property
    def pressure(self):
        if self.ttft_ratio is None or self.e2e_ratio is None:
            return None
        return max(self.ttft_ratio, self.e2e_ratio)


@dataclass(frozen=True)
class Window:
    start: float
    end: float
    revision: int
    offered_rps: float
    classes: dict[str, ClassEvidence]
    timed_out: int = 0


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    rate: float
    proposal_id: int | None = None


class Feedback:
    def __init__(self, required_classes, config=Config()):
        self.required = frozenset(required_classes)
        if not self.required or any(not isinstance(c, str) or not c for c in self.required):
            raise ValueError('required classes must be nonempty names')
        self.config = config
        self.rate = config.initial
        self.revision = 0
        self.ready_at = 0.0
        self.last_end = 0.0
        self.healthy = 0
        self.pending = None
        self.pending_end = 0.0
        self.serial = 0
        self.acknowledged_at = None

    def observe(self, window):
        if (not all(math.isfinite(v) for v in (window.start, window.end, window.offered_rps))
                or window.start < 0 or window.end <= window.start or window.offered_rps < 0
                or type(window.revision) is not int or window.revision < 0
                or type(window.timed_out) is not int or window.timed_out < 0):
            raise ValueError('invalid window')
        def hold(reason):
            return Decision('hold', reason, self.rate)
        if self.pending is not None:
            return hold('actuation_pending')
        if window.revision != self.revision:
            return hold('wrong_revision')
        if window.start < self.last_end:
            return hold('overlapping_or_old_window')
        if window.start > self.last_end:
            self.healthy = 0
        self.last_end = window.end
        if window.start < self.ready_at:
            self.healthy = 0
            return hold('settling_evidence')
        samples = [window.classes.get(name) for name in self.required]
        enough = lambda c: c is not None and c.completed + c.failed >= self.config.minimum_samples
        bad = window.timed_out > 0 or any(enough(c) and (c.failed > 0 or (c.pressure is not None and c.pressure > 1))
                  for c in samples)
        if bad:
            self.healthy = 0
            target = max(self.config.minimum, self.rate * self.config.decrease_factor)
            reason = 'request_timeout' if window.timed_out else 'observed_slo_or_backend_failure'
        else:
            if not all(enough(c) and c.pressure is not None and c.failed == 0 for c in samples):
                self.healthy = 0
                return hold('insufficient_class_evidence')
            if (window.offered_rps < self.rate * self.config.demand_fraction
                    or any(c.pressure >= self.config.grow_below for c in samples)):
                self.healthy = 0
                return hold('low_demand_or_deadband')
            self.healthy += 1
            if self.healthy < self.config.confirmations:
                return hold('awaiting_confirmation')
            self.healthy = 0
            target = min(self.config.maximum, self.rate + self.config.additive_step)
            reason = 'fresh_headroom_and_demand'
        if target == self.rate:
            return hold('rate_bound')
        self.serial += 1
        self.pending = Decision('decrease' if target < self.rate else 'increase', reason, target, self.serial)
        self.pending_end = window.end
        return self.pending

    def acknowledge(self, proposal_id, success, applied_at):
        if (self.pending is None or self.pending.proposal_id != proposal_id
                or type(success) is not bool or not math.isfinite(applied_at)
                or applied_at < self.pending_end):
            raise ValueError('invalid acknowledgement')
        if success:
            self.rate = self.pending.rate
            self.revision += 1
        self.pending = None
        self.healthy = 0
        self.ready_at = applied_at + self.config.settle_seconds
        self.acknowledged_at = applied_at
