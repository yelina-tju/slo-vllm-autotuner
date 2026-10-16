"""Ordered start/end event adapter. Caller supplies a monotonic watermark.

This is an integration contract, not a polling adapter for v1 /events (which
does not expose starts or admission revisions). Reject late/duplicate events.
"""
import math
from feedback import ClassEvidence, Window


def p99(values):
    values = sorted(values)
    return values[max(0, math.ceil(.99 * len(values)) - 1)] if values else None


class EventWindows:
    def __init__(self, limits, origin=0.0):
        if not limits or any(not math.isfinite(v) or v <= 0 for pair in limits.values() for v in pair):
            raise ValueError('positive class TTFT/E2E limits required')
        self.limits = limits
        self.start = origin
        self.clock = origin
        self.seen = set()
        self.pending = {}
        self.done = []
        self.offered = 0
        self.revisions = set()

    def _time(self, now):
        if not math.isfinite(now) or now < self.clock:
            raise ValueError('late or invalid event/watermark')
        self.clock = now

    def begin(self, request_id, now, shape, revision, admitted):
        if request_id in self.seen or shape not in self.limits:
            raise ValueError('duplicate request or unknown class')
        if type(revision) is not int or revision < 0 or type(admitted) is not bool:
            raise ValueError('invalid admission metadata')
        self._time(now)
        self.seen.add(request_id)
        self.offered += 1
        self.revisions.add(revision)
        if admitted:
            self.pending[request_id] = (now, shape, revision)

    def end(self, request_id, now, success, ttft_ms, e2el_ms):
        if request_id not in self.pending or type(success) is not bool:
            raise ValueError('unmatched completion')
        if not math.isfinite(e2el_ms) or e2el_ms < 0 or (ttft_ms is not None and (not math.isfinite(ttft_ms) or ttft_ms < 0)):
            raise ValueError('invalid latency')
        self._time(now)
        started, shape, revision = self.pending.pop(request_id)
        self.revisions.add(revision)
        self.done.append((shape, revision, success, ttft_ms, e2el_ms))

    def close(self, now, revision):
        if now <= self.start:
            raise ValueError('empty window')
        self._time(now)
        mixed = bool(self.revisions - {revision})
        # Conservative: no growth or latency inference with incomplete streams.
        blocked = mixed or bool(self.pending)
        classes = {}
        if not blocked:
            for shape, (ttft_slo, e2e_slo) in self.limits.items():
                rows = [r for r in self.done if r[0] == shape]
                good = [r for r in rows if r[2]]
                ttft = p99([r[3] / ttft_slo for r in good if r[3] is not None])
                if any(r[3] is None for r in good):
                    ttft = None
                classes[shape] = ClassEvidence(len(good), len(rows)-len(good), ttft,
                                               p99([r[4] / e2e_slo for r in good]))
        window = Window(self.start, now, revision, self.offered/(now-self.start), classes)
        audit = dict(pending=len(self.pending), mixed_revision=mixed,
                     oldest_pending_s=max((now-r[0] for r in self.pending.values()), default=0),
                     blocked=blocked)
        self.start = now
        self.done.clear()
        self.offered = 0
        self.revisions = {r[2] for r in self.pending.values()}
        return window, audit
