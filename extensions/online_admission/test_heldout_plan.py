import copy
from pathlib import Path
import tempfile
import unittest
from heldout_plan import CONFIG, plan, make_trace, validate, check_summary, prerequisites
from recovery_plan import CONFIG as DEVELOPMENT


class HeldoutPlanTest(unittest.TestCase):
    def summary(self):
        return dict(status='linked_evidence_verified', new_cases=4, preserved_cases=2, offered_records=71364,
                    verdict=dict(status='recovery_replicated'),
                    cases=[dict(seed=o['seed'], arm=a) for o in DEVELOPMENT['orders'] for a in o['arms']])

    def test_six_unseen_seed_cases(self):
        self.assertEqual(len(plan()), 6)
        self.assertEqual({c['seed'] for c in plan()}, {401, 402})
        self.assertEqual(len({(c['seed'], c['arm']) for c in plan()}), 6)

    def test_only_protocol_and_orders_differ(self):
        for key in DEVELOPMENT:
            if key not in ('protocol', 'orders'):
                self.assertEqual(CONFIG[key], DEVELOPMENT[key])
        bad = copy.deepcopy(CONFIG)
        bad['feedback']['decrease_factor'] = .5
        with self.assertRaises(ValueError): validate(bad)

    def test_trace_reproducible_and_bounded(self):
        for seed in (401, 402):
            rows = make_trace(seed)
            self.assertEqual(rows, make_trace(seed))
            self.assertTrue(all(0 < r['at'] < 240 for r in rows))
            self.assertLessEqual(len(rows), 14000)
        with self.assertRaises(ValueError): make_trace(309)

    def test_missing_evidence_blocks(self):
        with tempfile.TemporaryDirectory() as name:
            result = prerequisites(Path(name)/'archive', Path(name)/'audit')
            self.assertEqual(result['status'], 'blocked_missing_evidence')
            self.assertFalse(result['gpu_launch_allowed'])

    def test_partial_or_unreplicated_result_rejected(self):
        result = self.summary()
        check_summary(result)
        for key, value in [('status', 'completed_prefix_verified'), ('new_cases', 3), ('offered_records', 23578)]:
            with self.assertRaises(ValueError): check_summary({**result, key: value})
        result['verdict']['status'] = 'recovery_not_replicated'
        with self.assertRaises(ValueError): check_summary(result)

    def test_duplicate_development_cases_rejected(self):
        result = self.summary()
        result['cases'][-1] = result['cases'][0]
        with self.assertRaises(ValueError): check_summary(result)


if __name__ == '__main__': unittest.main()
