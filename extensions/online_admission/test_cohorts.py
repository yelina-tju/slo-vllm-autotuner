import unittest
from cohorts import ArrivalCohorts
from feedback import Feedback, Config


class CohortsTest(unittest.TestCase):
    def make(self, **kwargs):
        return ArrivalCohorts({'short': (100, 200)}, **kwargs)

    def test_later_pending_does_not_block_finished_cohort(self):
        a = self.make()
        a.begin(1, 0, 'short', 0, True)
        a.end(1, 1, True, 20, 100)
        a.begin(2, 10, 'short', 0, True)
        windows = a.advance(10, 0)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0][0].classes['short'].completed, 1)
        self.assertEqual(a.requests[2]['state'], 'pending')

    def test_wait_timeout_late_completion_and_no_double_count(self):
        a = self.make(timeout=15)
        a.begin(1, 9, 'short', 0, True)
        self.assertEqual(a.advance(10, 0), [])
        self.assertEqual(a.advance(23, 0), [])
        windows = a.advance(24, 0)
        w = windows[0][0]
        self.assertEqual((w.timed_out, w.classes['short'].failed), (1, 1))
        f = Feedback(['short'])
        self.assertEqual(f.observe(w).reason, 'request_timeout')
        self.assertFalse(a.end(1, 25, True, 50, 16000))
        self.assertEqual(a.advance(25, 0), [])
        with self.assertRaises(ValueError):
            a.end(1, 26, True, 50, 17000)

    def test_old_and_mixed_revisions_cannot_promote(self):
        a = self.make()
        a.begin(1, 0, 'short', 0, False)
        a.begin(2, 1, 'short', 1, False)
        w, audit = a.advance(10, 1)[0]
        self.assertTrue(audit['mixed_revision'])
        self.assertEqual(w.classes, {})
        a.begin(3, 10, 'short', 1, True)
        a.end(3, 11, True, 20, 100)
        w, _ = a.advance(20, 2)[0]
        f = Feedback(['short'])
        f.revision = 2
        self.assertEqual(f.observe(w).reason, 'wrong_revision')

    def test_continuous_stream_can_propose_growth(self):
        a = self.make()
        f = Feedback(['short'], Config(minimum_samples=1))
        for t in range(21):
            if t:
                a.end(t-1, t, True, 20, 100)
            a.begin(t, t, 'short', 0, True)
            # Rejected offered traffic still expresses demand.
            for j in range(3):
                a.begin(('reject', t, j), t, 'short', 0, False)
            for w, _ in a.advance(t, 0):
                d = f.observe(w)
        self.assertEqual(d.action, 'increase')
        self.assertEqual(a.requests[20]['state'], 'pending')

    def test_bounds_validation_and_deadline_boundary(self):
        with self.assertRaises(ValueError):
            self.make(width=0)
        a = self.make(timeout=1, max_requests=1)
        a.begin(1, 0, 'short', 0, True)
        self.assertFalse(a.end(1, 1, True, 10, 1000))
        with self.assertRaises(RuntimeError):
            a.begin(2, 2, 'short', 0, True)
