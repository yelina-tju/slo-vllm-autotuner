import unittest
from recovery_diagnostics import action_timing


class TimingTest(unittest.TestCase):
    def test_clock_origin_and_delay_units(self):
        record = dict(decision=dict(action='decrease', rate=33.6),
                      window=dict(start=140, end=160), audit=dict(emitted_at=160.5),
                      acknowledged_at=160.501, settling_ready_at=180.501)
        result = action_timing(record, 100)
        self.assertEqual(result['evidence_start'], 40)
        self.assertEqual(result['outcome_finalization_lag_s'], .5)
        self.assertAlmostEqual(result['acknowledgment_after_evidence_ms'], 1)
        self.assertAlmostEqual(result['settling_ready_at'], 80.501)


if __name__ == '__main__': unittest.main()
