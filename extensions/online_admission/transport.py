"""Opt-in streaming HTTP pilot client, not a public proxy or v1 replacement.

One event loop and one feedback owner. Backend configuration remains fixed.
"""
import asyncio
import time
import aiohttp
from slo_autotuner.executor import AdmissionRejected
from slo_autotuner.gateway import CompletionSseTracker
from hot_gate import apply_proposal
from feedback import Decision


class StreamingPilot:
    def __init__(self, executor, feedback, cohorts):
        self.executor, self.feedback, self.cohorts = executor, feedback, cohorts
        self.serial = 0
        self._tick_lock = asyncio.Lock()

    async def request(self, session, url, payload, shape, request_tag=None):
        if shape not in self.cohorts.limits or len(self.cohorts.requests) >= self.cohorts.max_requests:
            raise ValueError('unknown shape or pilot run exhausted')
        self.serial += 1
        request_id = self.serial
        gate = self.executor.admission_gate
        # This short critical section makes admission revision attribution atomic
        # with rate/lifecycle changes. Never hold the lock during network I/O.
        async with self.executor._lock:
            if len(self.cohorts.requests) >= self.cohorts.max_requests:
                raise ValueError('pilot run exhausted')
            try:
                await gate.acquire()
            except AdmissionRejected as exc:
                now = time.monotonic()
                self.cohorts.begin(request_id, now, shape, self.feedback.revision, False)
                return dict(request_id=request_id, status=exc.status, success=False, admitted=False,
                            started_at_s=now, completed_at_s=now, admission_revision=self.feedback.revision,
                            evidence_epoch=getattr(self.cohorts, 'epoch', None))
            started = time.monotonic()
            admission_revision = self.feedback.revision
            evidence_epoch = getattr(self.cohorts, 'epoch', None)
            try:
                self.cohorts.begin(request_id, started, shape, self.feedback.revision, True)
            except BaseException:
                await gate.release()
                raise
        tracker = CompletionSseTracker()
        first = None
        success = False
        status = 0
        error = None
        try:
            async with asyncio.timeout(self.cohorts.timeout):
                async with session.post(url, json={**payload, 'stream': True},
                                        headers={} if request_tag is None else {'X-Request-Id': request_tag}) as response:
                    status = response.status
                    if status == 200:
                        async for chunk in response.content.iter_any():
                            if tracker.feed(chunk) and first is None:
                                first = time.monotonic()
                        if tracker.finish() and first is None:
                            first = time.monotonic()
                        success = tracker.seen_token and tracker.seen_done
        except (TimeoutError, aiohttp.ClientError) as exc:
            error = type(exc).__name__
        finally:
            ended = time.monotonic()
            try:
                self.cohorts.end(request_id, ended, success,
                                 None if first is None else (first-started)*1000,
                                 (ended-started)*1000)
            finally:
                await gate.release()
        outcome = self.cohorts.requests[request_id]['state']
        return dict(request_id=request_id, status=status, success=success and outcome == 'success',
                    admitted=True, error=error, outcome=outcome,
                    started_at_s=started, completed_at_s=ended, admission_revision=admission_revision,
                    evidence_epoch=evidence_epoch,
                    ttft_ms=None if first is None else (first-started)*1000,
                    e2el_ms=(ended-started)*1000)

    async def tick(self, actuation_deadline=None):
        async with self._tick_lock:
            return await self._tick_locked(actuation_deadline)

    async def _tick_locked(self, actuation_deadline):
        records = []
        # Snapshot revision; a later ack makes remaining old cohorts ineligible.
        windows = self.cohorts.advance(time.monotonic(), self.feedback.revision)
        for window, audit in windows:
            evidence_status = self.cohorts.evidence_status(audit) if hasattr(self.cohorts, 'evidence_status') else None
            if evidence_status:
                decision = Decision('hold', evidence_status, self.feedback.rate)
            elif actuation_deadline is not None and time.monotonic() >= actuation_deadline:
                decision = Decision('hold', 'drain_only', self.feedback.rate)
            else:
                decision = self.feedback.observe(window)
            applied = None
            if decision.proposal_id is not None:
                applied = await apply_proposal(self.executor, self.feedback, decision,
                                               not_after=actuation_deadline)
                if hasattr(self.cohorts, 'reset_evidence'):
                    # Ack (including rejection) defines a new settling epoch.
                    # No await between acknowledgement and epoch reset.
                    self.cohorts.reset_evidence(self.feedback.ready_at, self.feedback.revision,
                                               self.feedback.acknowledged_at)
            records.append(dict(window=window, audit=audit, decision=decision, applied=applied,
                                feedback_revision=self.feedback.revision,
                                acknowledged_at=self.feedback.acknowledged_at,
                                settling_ready_at=self.feedback.ready_at,
                                current_evidence_epoch=getattr(self.cohorts, 'epoch', None)))
        return records
