import unittest
from alignment_cost import timing


class AlignmentTest(unittest.TestCase):
    def test_boundary_discontinuity(self):
        self.assertEqual(timing(60, 0, 20, 2)['alignment_wait'], 0)
        self.assertAlmostEqual(timing(60.1, 0, 20, 2)['alignment_wait'], 19.9)
        self.assertEqual(timing(60.1, 0, 20, 2)['earliest_confirmation'], 120)

    def test_never_uses_presettling_evidence(self):
        for offset in range(2001):
            ready = 40+offset/100
            result = timing(ready, 0, 20, 2)
            self.assertGreaterEqual(result['first_eligible_start'], ready)
            self.assertTrue(0 <= result['alignment_wait'] < 20)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            timing(0, 0, 0, 2)
