import unittest
from events import EventWindows


class EventsTest(unittest.TestCase):
    def test_rejections_count_demand_not_failures(self):
        e = EventWindows({'short': (100, 200)})
        e.begin(1, 0, 'short', 0, False)
        e.begin(2, 1, 'short', 0, True)
        e.end(2, 2, True, 50, 100)
        w, audit = e.close(10, 0)
        self.assertEqual(w.offered_rps, .2)
        self.assertEqual(w.classes['short'].completed, 1)
        self.assertEqual(w.classes['short'].failed, 0)
        self.assertEqual(w.classes['short'].pressure, .5)
        self.assertFalse(audit['blocked'])

    def test_pending_and_old_revision_block(self):
        e = EventWindows({'short': (100, 200)})
        e.begin(1, 0, 'short', 0, True)
        w, a = e.close(10, 0)
        self.assertEqual(w.classes, {})
        self.assertEqual(a['oldest_pending_s'], 10)
        e.end(1, 11, False, None, 11000)
        w, a = e.close(20, 1)
        self.assertTrue(a['mixed_revision'])
        self.assertEqual(w.classes, {})

    def test_duplicate_late_and_missing_latency(self):
        e = EventWindows({'short': (100, 200)})
        e.begin(1, 1, 'short', 0, True)
        with self.assertRaises(ValueError):
            e.begin(1, 2, 'short', 0, True)
        with self.assertRaises(ValueError):
            e.end(1, 0, True, 1, 1)
        e.end(1, 2, True, None, 100)
        w, _ = e.close(10, 0)
        self.assertIsNone(w.classes['short'].pressure)
        with self.assertRaises(ValueError):
            e.end(1, 11, True, 1, 1)
