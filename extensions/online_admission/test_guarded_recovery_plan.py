import copy
import unittest
from guarded_recovery_plan import CONFIG, validate, make_trace, phase_accounting, initial_gate, action_attribution
from recovery_plan import CONFIG as OLD


class GuardedPlanTest(unittest.TestCase):
    profile = dict(ttft_slo_ms=100, e2el_slo_ms=400)

    def row(self, at, end=None, e2e=200, success=True, admitted=True):
        return dict(scheduled_at_s=at, started_at_s=100+at,
                    completed_at_s=100+(end if end is not None else at+.2),
                    success=success, admitted=admitted, ttft_ms=20, e2el_ms=e2e, dispatch_lag_s=0)

    def initial(self):
        return [self.row(start+i*.5) for start in (0, 20) for i in range(30)]

    def test_only_protocol_phase_and_seeds_change(self):
        validate(CONFIG)
        for key in OLD:
            if key not in ('protocol', 'phases', 'orders'):
                self.assertEqual(CONFIG[key], OLD[key])
        bad = copy.deepcopy(CONFIG)
        bad['feedback']['decrease_factor'] = .5
        with self.assertRaises(ValueError): validate(bad)

    def test_registered_deterministic_traces(self):
        for seed in (403, 404):
            trace = make_trace(seed)
            self.assertEqual(trace, make_trace(seed))
            self.assertTrue(all(0 < r['at'] < 260 for r in trace))
            self.assertLessEqual(len(trace), 14000)
        with self.assertRaises(ValueError): make_trace(401)

    def test_guard_violation_not_removed(self):
        rows = self.initial()+[self.row(59.9, 60.4, e2e=500)]
        accounting = phase_accounting(rows, self.profile)
        self.assertEqual(accounting['whole']['violations'], 1)
        self.assertEqual(accounting['phases']['guard']['violations'], 1)
        self.assertEqual(accounting['whole']['scheduled_goodput'], 60/260)
        self.assertTrue(initial_gate(rows, 100, self.profile)['healthy'])

    def test_initial_violation_is_still_failure(self):
        rows = self.initial()+[self.row(39.9, 40.4, e2e=500), self.row(39.8, 40.3, e2e=500)]
        self.assertFalse(initial_gate(rows, 100, self.profile)['healthy'])

    def test_timeout_assumption_cannot_replace_observation(self):
        rows = self.initial()+[self.row(39.9, 60, success=False)]
        gate = initial_gate(rows, 100, self.profile)
        self.assertFalse(gate['finalized_before_high'])
        self.assertFalse(gate['healthy'])

    def test_empty_or_missing_window_rejected(self):
        for rows in ([], self.initial()[:30]):
            self.assertFalse(initial_gate(rows, 100, self.profile)['healthy'])

    def test_exact_phase_boundaries_and_failures_conserved(self):
        rows = [self.row(0), self.row(40, success=False), self.row(60, success=False, admitted=False), self.row(220)]
        result = phase_accounting(rows, self.profile)
        self.assertEqual([p['offered'] for p in result['phases'].values()], [1]*4)
        self.assertEqual(result['whole']['failures'], 1)
        self.assertEqual(result['whole']['rejected'], 1)
        with self.assertRaises(ValueError): phase_accounting([self.row(260)], self.profile)

    def test_action_time_does_not_relabel_evidence(self):
        result = action_attribution(dict(at=60.6, evidence_start=40, evidence_end=60))
        self.assertTrue(result['acknowledged_during_high'])
        self.assertEqual(result['evidence_membership'], 'pre_high_arrivals')
        self.assertEqual(action_attribution(dict(at=80.5, evidence_start=60, evidence_end=80))['evidence_membership'], 'fully_high_arrivals')
        self.assertEqual(action_attribution(dict(at=70.5, evidence_start=50, evidence_end=70))['evidence_membership'], 'boundary_or_other')


if __name__ == '__main__': unittest.main()
