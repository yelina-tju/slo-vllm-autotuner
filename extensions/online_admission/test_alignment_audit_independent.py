"""No HTTP/GPU dependencies: reject corrupted accounting evidence."""
import copy
import unittest

from audit_alignment_pairs import check_members, p99


class IndependentAuditTest(unittest.TestCase):
    def setUp(self):
        self.profile = dict(name='short', ttft_slo_ms=100, e2el_slo_ms=200)
        self.rows = [dict(admitted=True, admission_revision=1, success=True,
                          ttft_ms=50, e2el_ms=100)]
        self.window = dict(revision=1, timed_out=0, classes=dict(short=dict(
            completed=1, failed=0, ttft_ratio=.5, e2e_ratio=.5)))
        self.audit = dict(offered=1, finalized=1, mixed_revision=False, timed_out=0)

    def check(self, window=None, audit=None, rows=None):
        check_members(window or self.window, audit or self.audit,
                      self.rows if rows is None else rows, self.profile)

    def test_valid(self):
        self.check()

    def test_corrupt_count_fields(self):
        for field in ('offered', 'finalized', 'timed_out'):
            with self.subTest(field=field):
                bad = {**self.audit, field: 9}
                with self.assertRaises(ValueError):
                    self.check(audit=bad)

    def test_corrupt_quantile_and_outcomes(self):
        for field in ('completed', 'failed', 'ttft_ratio', 'e2e_ratio'):
            with self.subTest(field=field):
                bad = copy.deepcopy(self.window)
                bad['classes']['short'][field] = 9
                with self.assertRaises(ValueError):
                    self.check(window=bad)

    def test_mixed_revision_requires_exclusion(self):
        rows = self.rows + [dict(admitted=False, admission_revision=2)]
        audit = {**self.audit, 'offered': 2, 'mixed_revision': True}
        with self.assertRaisesRegex(ValueError, 'mixed evidence'):
            self.check(audit=audit, rows=rows)
        self.check(window={**self.window, 'classes': {}}, audit=audit, rows=rows)

    def test_timeout_cannot_be_relabelled_success(self):
        rows = [dict(admitted=True, admission_revision=1, success=False, outcome='timeout')]
        with self.assertRaisesRegex(ValueError, 'timeout'):
            self.check(rows=rows)

    def test_nearest_rank_p99(self):
        self.assertIsNone(p99([]))
        self.assertEqual(p99(range(100)), 98)
        self.assertEqual(p99([1, 9]), 9)


if __name__ == '__main__':
    unittest.main()
