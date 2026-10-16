"""Opt-in v2 gate; frozen v1 gate is unchanged."""
import math
import time
from slo_autotuner.executor import AdmissionGate


class HotAdmissionGate(AdmissionGate):
    async def update_rate(self, rate, now=None, not_after=None):
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError('rate must be finite and positive')
        async with self._condition:
            if self._paused:
                return False
            now = time.monotonic() if now is None else now
            if not math.isfinite(now) or now < self._last_refill_s:
                raise ValueError('invalid update time')
            if not_after is not None:
                if not math.isfinite(not_after):
                    raise ValueError('invalid actuation deadline')
                if now >= not_after:
                    return False
            self._refill(now)  # Accrue elapsed time at OLD rate, never gift a burst.
            self._rate_limit_rps = rate
            self._capacity = max(1.0, rate * self._burst_seconds)
            self._tokens = min(self._tokens, self._capacity)
            return True


async def apply_proposal(executor, feedback, decision, not_after=None):
    """Single feedback owner required; share the lifecycle executor's lock.

    Gate and controller must be initialized to the same rate. Lifecycle policy
    changes require rebuilding feedback; mismatch fails closed here.
    """
    async with executor._lock:
        if feedback.pending != decision:
            raise ValueError('proposal is not pending')
        gate = executor.admission_gate
        applied = False
        if gate.rate_limit_rps == feedback.rate:
            applied = await gate.update_rate(decision.rate, not_after=not_after)
        feedback.acknowledge(decision.proposal_id, applied, time.monotonic())
        return applied
