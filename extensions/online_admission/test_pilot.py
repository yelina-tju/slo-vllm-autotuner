import unittest
from run_pilot import trace, score


class PilotTest(unittest.TestCase):
    def test_trace_is_reproducible_and_bounded(self):
        cfg = dict(seed=201, phases=[dict(seconds=40, rps=6), dict(seconds=40, rps=10)])
        a, duration = trace(cfg)
        self.assertEqual((a, duration), trace(cfg))
        self.assertEqual(duration, 80)
        self.assertTrue(all(0 <= row['at'] < 80 for row in a))
        self.assertEqual(sorted(r['at'] for r in a), [r['at'] for r in a])
        with self.assertRaises(ValueError):
            trace(dict(seed=1, phases=[dict(seconds=1, rps=0)]))

    def test_rejections_and_dispatch_delay_do_not_inflate_goodput(self):
        rows = [dict(status=200, success=True, ttft_ms=50, e2el_ms=100, dispatch_lag_s=.2),
                dict(status=429, success=False, dispatch_lag_s=0)]
        result = score(rows, 10, (100, 200))
        self.assertEqual(result['service_goodput'], .1)
        self.assertEqual(result['scheduled_goodput'], 0)
