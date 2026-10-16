import copy
import unittest
from guarded_recovery_analysis import recovery_gate, verdict


class GuardedGateTest(unittest.TestCase):
    def action(self):
        return dict(action='decrease', at=60.6, ready=80.6, revision=1,
                    evidence_start=40, evidence_end=60)

    def windows(self):
        return [dict(start=80.6+i*20, end=100.6+i*20, emitted_at=101+i*20,
                     revision=1, epoch=1, healthy=True) for i in range(3)]

    def test_operational_recovery_from_boundary_evidence(self):
        result = recovery_gate(self.windows(), [self.action()])
        self.assertTrue(result['recovered'])
        self.assertEqual(result['recovery_from_high_start_s'], 61)

    def test_pre_high_action_not_counted(self):
        action = self.action()
        action['at'] = 59.9
        self.assertFalse(recovery_gate(self.windows(), [action])['recovered'])

    def test_confirmation_after_high_rejected(self):
        windows = self.windows()[:2]
        windows[-1]['emitted_at'] = 220.1
        self.assertFalse(recovery_gate(windows, [self.action()])['recovered'])

    def test_later_failure_and_stale_windows_rejected(self):
        windows = self.windows()
        windows[-1]['healthy'] = False
        self.assertFalse(recovery_gate(windows, [self.action()])['recovered'])
        for field, value in [('revision', 0), ('epoch', 2), ('start', 121)]:
            windows = self.windows()[:2]
            windows[-1][field] = value
            self.assertFalse(recovery_gate(windows, [self.action()])['recovered'])

    def cases(self):
        return [dict(seed=s, arm=a, before_healthy=True, low_anchor_reproduced=True,
                     high_anchor_reproduced=True, recovery=dict(recovered=True),
                     actions=[self.action()] if a == 'adaptive' else [], goodput=1,
                     completed_slo_violations=2, rejections=3)
                for s in (403, 404) for a in ('low', 'high', 'adaptive')]

    def test_recovery_does_not_imply_high_evidence_detection(self):
        result = verdict(self.cases())
        self.assertEqual(result['status'], 'recovery_replicated')
        self.assertFalse(result['pairs'][0]['fully_high_decrease_observed'])
        cases = self.cases()
        cases[2]['actions'][0].update(evidence_start=60, evidence_end=80, at=80.6)
        self.assertTrue(verdict(cases)['pairs'][0]['fully_high_decrease_observed'])

    def test_baseline_failure_preserved(self):
        cases = self.cases()
        cases[0]['before_healthy'] = False
        self.assertEqual(verdict(cases)['status'], 'inconclusive_baseline')

    def test_both_seeds_and_exact_cases_required(self):
        cases = self.cases()
        cases[-1]['recovery']['recovered'] = False
        self.assertEqual(verdict(cases)['status'], 'recovery_not_replicated')
        with self.assertRaises(ValueError): verdict(cases[:-1])
        cases[-1] = copy.deepcopy(cases[0])
        with self.assertRaises(ValueError): verdict(cases)


if __name__ == '__main__': unittest.main()
