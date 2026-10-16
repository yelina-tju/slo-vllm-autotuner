import copy
import json
from pathlib import Path
import unittest
from run_alignment_pairs import validate
from audit_alignment_pairs import check_members


class PairProtocolTest(unittest.TestCase):
    def test_reverse_order_and_seed_bounds(self):
        cfg = json.loads(Path(__file__).with_name('alignment_pairs_config.json').read_text())
        validate(cfg)
        bad = copy.deepcopy(cfg)
        bad['pairs'][1]['order'] = bad['pairs'][0]['order']
        with self.assertRaises(ValueError):
            validate(bad)

    def test_independent_membership_reconstruction(self):
        profile = dict(name='short', ttft_slo_ms=100, e2el_slo_ms=200)
        rows = [dict(admitted=True, admission_revision=1, success=True, ttft_ms=50, e2el_ms=100)]
        window = dict(revision=1, timed_out=0, classes=dict(short=dict(completed=1, failed=0, ttft_ratio=.5, e2e_ratio=.5)))
        a = dict(offered=1, finalized=1, mixed_revision=False, timed_out=0)
        check_members(window, a, rows, profile)
        with self.assertRaisesRegex(ValueError, 'offered count'):
            check_members(window, a, rows+rows, profile)
        rows[0]['admission_revision'] = 0
        with self.assertRaisesRegex(ValueError, 'revision'):
            check_members(window, a, rows, profile)
