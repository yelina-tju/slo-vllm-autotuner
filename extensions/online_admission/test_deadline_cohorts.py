import unittest
from deadline_cohorts import DeadlineCohorts
from feedback import Feedback, Config
from cohorts import ArrivalCohorts


class DeadlineTest(unittest.TestCase):
    def make(self, **kwargs):
        return DeadlineCohorts({'short': (100, 200)}, width=20, **kwargs)

    def test_retired_request_still_times_out_in_accounting(self):
        c = self.make(timeout=15)
        c.begin('old', 0, 'short', 0, True)
        c.reset_evidence(10, 1, 1)
        c.begin('cooldown', 2, 'short', 1, False)
        c.begin('new', 10, 'short', 1, True)
        c.end('new', 11, True, 20, 100)
        rows = c.advance(30, 1)
        accounting = [(w, a) for w, a in rows if a['purpose'] == 'accounting']
        evidence = [(w, a) for w, a in rows if a['purpose'] == 'evidence']
        self.assertEqual(sum(a['offered'] for _, a in accounting), 3)
        self.assertEqual(sum(a['timed_out'] for _, a in accounting), 1)
        self.assertEqual(evidence[0][0].classes['short'].completed, 1)
        self.assertEqual(evidence[0][0].timed_out, 0)
        self.assertFalse(c.end('old', 31, True, 20, 31000))

    def test_boundary_and_same_revision_failed_ack_retirement(self):
        c = self.make()
        c.begin(1, 0, 'short', 0, False)
        emitted = c.advance(20, 0)
        old = next(a for _, a in emitted if a['purpose'] == 'evidence')
        c.reset_evidence(40.1, 0, 20.1)
        self.assertEqual(c.evidence_status(old), 'retired_evidence')
        c.begin(2, 40.09, 'short', 0, False)
        c.begin(3, 40.1, 'short', 0, True)
        c.end(3, 41, True, 10, 100)
        evidence = [w for w, a in c.advance(60.1, 0) if a['purpose'] == 'evidence']
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].start, 40.1)
        self.assertEqual(evidence[0].classes['short'].completed, 1)
        self.assertEqual(len(c.requests), 3)

    def test_geometry_gain_without_lowering_safety_thresholds(self):
        c = self.make()
        f = Feedback(['short'], Config(minimum_samples=30, confirmations=2, settle_seconds=20))
        f.rate, f.revision, f.ready_at = 4, 1, 60.125
        c.reset_evidence(60.125, 1, 40.125)
        for start in (60.125, 80.125):
            for i in range(80):
                t = start+i*.2
                c.begin((start, i), t, 'short', 1, True)
                c.end((start, i), t+.05, True, 20, 100)
            for w, a in c.advance(start+20, 1):
                if c.evidence_status(a) is None:
                    d = f.observe(w)
        self.assertEqual(d.action, 'increase')
        self.assertEqual(f.pending_end, 100.125)
        self.assertEqual(f.rate, 4)  # Still only a proposal; no fictitious actuation.

    def test_primary_bounds_and_validation_remain(self):
        c = self.make(max_requests=1)
        c.begin(1, 0, 'short', 0, False)
        c.reset_evidence(20, 1, 1)
        with self.assertRaises(RuntimeError):
            c.begin(2, 20, 'short', 1, True)
        with self.assertRaises(ValueError):
            c.reset_evidence(10, 2, 21)

    def test_identical_continuous_events_fixed_vs_anchored(self):
        def first_proposal(cls):
            c = cls({'short': (100, 200)}, width=20)
            f = Feedback(['short'])
            f.rate, f.revision, f.ready_at = 4, 1, 60.125
            if isinstance(c, DeadlineCohorts):
                c.reset_evidence(60.125, 1, 40.125)
            events = []
            for i in range(300):
                at = 60.125+i*.2
                events.extend([(at, 0, i), (at+.05, 1, i)])
            events.extend((t, 2, 0) for t in (80, 80.125, 100, 100.125, 120, 120.125))
            first = None
            for at, kind, request_id in sorted(events):
                if kind == 0:
                    c.begin(request_id, at, 'short', 1, True)
                elif kind == 1:
                    c.end(request_id, at, True, 20, 100)
                else:
                    for w, a in c.advance(at, 1):
                        if isinstance(c, DeadlineCohorts) and c.evidence_status(a):
                            continue
                        d = f.observe(w)
                        if d.action == 'increase' and first is None:
                            first = at
            return first
        self.assertEqual(first_proposal(ArrivalCohorts), 120)
        self.assertEqual(first_proposal(DeadlineCohorts), 100.125)
