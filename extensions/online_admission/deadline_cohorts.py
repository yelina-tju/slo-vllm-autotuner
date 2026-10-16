"""Opt-in deadline-anchored evidence with a separate immutable accounting grid.

All requests remain in the primary ledger. Only post-settling arrivals enter the
current evidence epoch; retiring that epoch never loses primary outcomes.
"""
import math
from cohorts import ArrivalCohorts


class DeadlineCohorts(ArrivalCohorts):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.epoch = 0
        self.evidence_revision = 0
        self.evidence_ready = self.origin
        self._new_lane()

    def _new_lane(self):
        self.lane = ArrivalCohorts(self.limits, origin=self.evidence_ready,
                                  width=self.width, timeout=self.timeout,
                                  max_requests=self.max_requests)

    def reset_evidence(self, ready_at, revision, now):
        if (not math.isfinite(ready_at) or ready_at < now
                or type(revision) is not int or revision < self.evidence_revision):
            raise ValueError('invalid evidence epoch')
        self._time(now)
        self.epoch += 1
        self.evidence_revision = revision
        self.evidence_ready = ready_at
        self._new_lane()

    def begin(self, request_id, now, shape, revision, admitted):
        super().begin(request_id, now, shape, revision, admitted)
        if now >= self.evidence_ready and revision == self.evidence_revision:
            self.lane.begin(request_id, now, shape, revision, admitted)

    def end(self, request_id, now, success, ttft_ms, e2el_ms):
        accepted = super().end(request_id, now, success, ttft_ms, e2el_ms)
        if request_id in self.lane.requests:
            self.lane.end(request_id, now, success, ttft_ms, e2el_ms)
        return accepted

    def advance(self, now, current_revision):
        accounting = super().advance(now, current_revision)
        records = [(w, {**a, 'purpose': 'accounting'}) for w, a in accounting]
        if now >= self.evidence_ready:
            records.extend((w, {**a, 'purpose': 'evidence', 'epoch': self.epoch})
                           for w, a in self.lane.advance(now, self.evidence_revision))
        return records

    def evidence_status(self, audit):
        if audit['purpose'] == 'accounting':
            return 'accounting_only'
        if audit['epoch'] != self.epoch:
            return 'retired_evidence'
        return None
