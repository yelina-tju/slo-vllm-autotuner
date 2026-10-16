"""Bounded-run arrival cohorts; no unfinished-request success imputation.

All calls must be serialized on one event loop and use the same monotonic clock.
Timeout is an accounting outcome, NOT cancellation of the actual backend task.
"""
from dataclasses import dataclass, field
import math
import heapq
from events import p99
from feedback import ClassEvidence, Window


@dataclass
class Cohort:
    offered: int = 0
    revisions: set = field(default_factory=set)
    requests: list = field(default_factory=list)


class ArrivalCohorts:
    def __init__(self, limits, origin=0.0, width=10.0, timeout=15.0, max_requests=100000):
        if any(not math.isfinite(v) for v in (origin, width, timeout)) or origin < 0 or min(width, timeout) <= 0:
            raise ValueError('invalid cohort timing')
        if not limits or any(len(pair) != 2 or any(not math.isfinite(v) or v <= 0 for v in pair) for pair in limits.values()):
            raise ValueError('invalid SLOs')
        if type(max_requests) is not int or max_requests < 1:
            raise ValueError('invalid run size limit')
        self.limits = dict(limits)
        self.origin, self.width, self.timeout = origin, width, timeout
        self.clock = origin
        self.max_requests = max_requests
        self.requests = {}
        self.deadlines = []
        self.buckets = {}
        self.next_index = 0

    def _time(self, now):
        if not math.isfinite(now) or now < self.clock:
            raise ValueError('late or invalid event')
        self.clock = now
        while self.deadlines and self.deadlines[0][0] <= now:
            _, _, request_id = heapq.heappop(self.deadlines)
            row = self.requests[request_id]
            if row['state'] == 'pending':
                row['state'] = 'timeout'

    def begin(self, request_id, now, shape, revision, admitted):
        if request_id in self.requests or shape not in self.limits:
            raise ValueError('duplicate ID or unknown class')
        if type(revision) is not int or revision < 0 or type(admitted) is not bool:
            raise ValueError('invalid admission metadata')
        if len(self.requests) >= self.max_requests:
            raise RuntimeError('bounded run exhausted; stop admission and archive')
        self._time(now)
        index = math.floor((now-self.origin)/self.width)
        cohort = self.buckets.setdefault(index, Cohort())
        cohort.offered += 1
        cohort.revisions.add(revision)
        row = dict(shape=shape, state='pending' if admitted else 'rejected',
                   deadline=now+self.timeout, ttft=None, e2e=None)
        self.requests[request_id] = row
        if admitted:
            cohort.requests.append(row)
            heapq.heappush(self.deadlines, (row['deadline'], len(self.requests), request_id))

    def end(self, request_id, now, success, ttft_ms, e2el_ms):
        row = self.requests.get(request_id)
        if row is None or row['state'] not in ('pending', 'timeout') or type(success) is not bool:
            raise ValueError('unmatched completion')
        if not math.isfinite(e2el_ms) or e2el_ms < 0 or (ttft_ms is not None and (not math.isfinite(ttft_ms) or not 0 <= ttft_ms <= e2el_ms)):
            raise ValueError('invalid latency')
        self._time(now)
        if row['state'] == 'timeout':
            if row.get('late_seen'):
                raise ValueError('duplicate late completion')
            row['late_seen'] = True
            return False  # Cannot rewrite a timeout into a success.
        row.update(state='success' if success else 'failure', ttft=ttft_ms, e2e=e2el_ms)
        return True

    def advance(self, now, current_revision):
        if type(current_revision) is not int or current_revision < 0:
            raise ValueError('invalid revision')
        self._time(now)
        output = []
        while self.origin+(self.next_index+1)*self.width <= now:
            cohort = self.buckets.get(self.next_index, Cohort())
            if any(r['state'] == 'pending' for r in cohort.requests):
                break  # Ordered delivery; bounded by request timeout.
            start = self.origin+self.next_index*self.width
            revisions = cohort.revisions
            mixed = len(revisions) > 1
            revision = next(iter(revisions)) if len(revisions) == 1 else current_revision
            classes = {}
            timeouts = sum(r['state'] == 'timeout' for r in cohort.requests)
            if not mixed:
                for name, (ttft_slo, e2e_slo) in self.limits.items():
                    rows = [r for r in cohort.requests if r['shape'] == name]
                    good = [r for r in rows if r['state'] == 'success']
                    ttft = None if any(r['ttft'] is None for r in good) else p99([r['ttft']/ttft_slo for r in good])
                    classes[name] = ClassEvidence(len(good), len(rows)-len(good), ttft,
                                                 p99([r['e2e']/e2e_slo for r in good]))
            window = Window(start, start+self.width, revision, cohort.offered/self.width,
                            classes, 0 if mixed else timeouts)
            output.append((window, dict(emitted_at=now, mixed_revision=mixed,
                                        timed_out=timeouts, offered=cohort.offered,
                                        finalized=len(cohort.requests))))
            self.buckets.pop(self.next_index, None)
            self.next_index += 1
        return output
