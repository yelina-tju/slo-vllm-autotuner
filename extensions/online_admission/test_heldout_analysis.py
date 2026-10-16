import copy
import unittest
from heldout_analysis import verdict


class HeldoutVerdictTest(unittest.TestCase):
    def cases(self):
        return [dict(seed=s, arm=a, before_healthy=True, low_anchor_reproduced=True,
                     high_anchor_reproduced=True, recovery=dict(recovered=True),
                     goodput=3 if a == 'adaptive' else 4, rejections=10,
                     completed_slo_violations=8 if a == 'adaptive' else 0)
                for s in (401, 402) for a in ('low', 'high', 'adaptive')]

    def test_recovery_is_not_superiority(self):
        result = verdict(self.cases())
        self.assertEqual(result['status'], 'recovery_replicated')
        self.assertEqual(result['pairs'][0]['adaptive_minus_low_goodput'], -1)
        self.assertEqual(result['pairs'][0]['adaptive_minus_low_violations'], 8)

    def test_both_seeds_required(self):
        cases = self.cases()
        cases[-1]['recovery']['recovered'] = False
        self.assertEqual(verdict(cases)['status'], 'recovery_not_replicated')

    def test_invalid_baseline_is_inconclusive(self):
        for field, index in [('before_healthy', 2), ('low_anchor_reproduced', 0),
                             ('high_anchor_reproduced', 4)]:
            cases = self.cases()
            cases[index][field] = False
            self.assertEqual(verdict(cases)['status'], 'inconclusive_baseline')

    def test_missing_duplicate_and_development_seeds_rejected(self):
        original = self.cases()
        duplicate = copy.deepcopy(original)
        duplicate[-1] = duplicate[0]
        old = copy.deepcopy(original)
        for c in old:
            c['seed'] -= 92
        for cases in (original[:-1], duplicate, old):
            with self.assertRaises(ValueError):
                verdict(cases)

    def test_order_does_not_change_verdict(self):
        self.assertEqual(verdict(self.cases()), verdict(list(reversed(self.cases()))))


if __name__ == '__main__':
    unittest.main()
