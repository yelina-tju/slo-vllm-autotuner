import unittest
from recovery_plan import CONFIG, plan
from recovery_continuation import remaining_cases, reviewed_changes, REPAIRED_OWNER


class ContinuationTest(unittest.TestCase):
    def test_only_four_missing_cases(self):
        result = remaining_cases(plan(CONFIG)[:2])
        self.assertEqual(result, [dict(seed=309, arm='adaptive'), dict(seed=310, arm='adaptive'),
                                  dict(seed=310, arm='high'), dict(seed=310, arm='low')])
        self.assertFalse(any(c['seed'] == 309 and c['arm'] in ('low', 'high') for c in result))

    def test_wrong_prefix_rejected(self):
        for wrong in ([], plan(CONFIG)[:1], plan(CONFIG)[:3], list(reversed(plan(CONFIG)[:2]))):
            with self.assertRaises(ValueError): remaining_cases(wrong)

    def maps(self):
        old = {'owned_backend.py': 'old', 'run_recovery.py': 'oldrun', 'feedback.py': 'frozen'}
        new = {**old, 'owned_backend.py': REPAIRED_OWNER, 'run_recovery.py': 'newrun', 'new_audit.py': 'added'}
        return old, new

    def test_exact_reviewed_change_set(self):
        old, new = self.maps()
        self.assertEqual(set(reviewed_changes(old, new)), {'owned_backend.py', 'run_recovery.py'})

    def test_controller_change_rejected(self):
        old, new = self.maps()
        new['feedback.py'] = 'changed'
        with self.assertRaises(ValueError): reviewed_changes(old, new)

    def test_removed_code_or_different_repair_rejected(self):
        old, new = self.maps()
        del new['feedback.py']
        with self.assertRaises(ValueError): reviewed_changes(old, new)
        old, new = self.maps()
        new['owned_backend.py'] = 'other repair'
        with self.assertRaises(ValueError): reviewed_changes(old, new)


if __name__ == '__main__': unittest.main()
