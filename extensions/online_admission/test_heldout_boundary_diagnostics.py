import unittest
from heldout_boundary_diagnostics import summarize


class BoundaryDiagnosticTest(unittest.TestCase):
    def row(self, start, end, latency=450, success=True):
        return dict(started_at_s=100+start, completed_at_s=100+end,
                    scheduled_at_s=start, success=success, ttft_ms=20, e2el_ms=latency)

    def test_crossing_not_excluded(self):
        result = summarize([self.row(39.9, 40.4), self.row(39, 39.45)], 100,
                           dict(ttft_slo_ms=100, e2el_slo_ms=400))
        self.assertEqual(result['before_service_violations'], 2)
        self.assertEqual(result['violations_crossing_boundary'], 1)
        self.assertEqual(result['violations_completed_before_boundary'], 1)
        self.assertEqual(result['before_successes'], 2)

    def test_boundary_and_success_semantics(self):
        result = summarize([self.row(40, 40.45), self.row(39.9, 40, 100),
                            self.row(39.9, 40.5, success=False)], 100,
                           dict(ttft_slo_ms=100, e2el_slo_ms=400))
        self.assertEqual(result['before_offered'], 2)
        self.assertEqual(result['before_successes'], 1)
        self.assertEqual(result['crossing_successes'], 1)
        self.assertEqual(result['before_service_violations'], 0)


if __name__ == '__main__': unittest.main()
