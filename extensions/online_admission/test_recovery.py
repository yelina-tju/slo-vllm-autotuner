import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from recovery_plan import CONFIG, validate, plan, make_trace, case_config
from recovery_analysis import recovery_gate, stats, verdict


class RecoveryTest(unittest.TestCase):
    def test_frozen_plan_and_configuration(self):
        self.assertEqual(len(plan(CONFIG)), 6)
        bad = copy.deepcopy(CONFIG)
        bad['feedback']['grow_below'] = .9
        with self.assertRaises(ValueError): validate(bad)
        self.assertEqual(case_config(CONFIG, 309, 'low')[0]['fixed_rate'], 24)
        self.assertEqual(case_config(CONFIG, 310, 'adaptive')[1], 'adaptive_deadline')
        with self.assertRaises(ValueError): case_config(CONFIG, 307, 'low')

    def test_trace_and_safe_preview(self):
        for seed in (309, 310):
            trace = make_trace(seed)
            self.assertEqual(trace, make_trace(seed))
            self.assertLessEqual(len(trace), 14000)
            self.assertTrue(all(0 < r['at'] < 240 for r in trace))
        completed = subprocess.run([sys.executable, str(Path(__file__).with_name('run_recovery.py'))],
                                   capture_output=True, text=True, check=True)
        self.assertEqual(len(json.loads(completed.stdout)['cases']), 6)

    def fixtures(self):
        actions = [dict(action='decrease', at=60, ready=80, revision=1)]
        windows = [dict(start=80, end=100, emitted_at=101, epoch=1, revision=1, healthy=True),
                   dict(start=100, end=120, emitted_at=121, epoch=1, revision=1, healthy=True)]
        return windows, actions

    def test_fresh_consecutive_recovery(self):
        w, a = self.fixtures()
        self.assertEqual(recovery_gate(w, a)['recovery_at'], 121)

    def test_no_decrease_not_recovery(self):
        self.assertFalse(recovery_gate(self.fixtures()[0], [])['recovered'])

    def test_after_load_drop_not_recovery(self):
        w, a = self.fixtures()
        w[-1]['emitted_at'] = 201
        self.assertFalse(recovery_gate(w, a)['recovered'])

    def test_mixed_epochs_and_gaps_not_consecutive(self):
        for key, value in [('epoch', 2), ('start', 101), ('revision', 0)]:
            w, a = self.fixtures()
            w[-1][key] = value
            self.assertFalse(recovery_gate(w, a)['recovered'])

    def test_pre_settling_excluded(self):
        w, a = self.fixtures()
        a[0]['ready'] = 81
        self.assertFalse(recovery_gate(w, a)['recovered'])

    def test_later_breach_or_decrease_invalidates_early_success(self):
        w, a = self.fixtures()
        w.append(dict(start=120, end=140, emitted_at=141, epoch=1, revision=1, healthy=False))
        self.assertFalse(recovery_gate(w, a)['recovered'])
        w, a = self.fixtures()
        a.append(dict(action='decrease', at=141, ready=161, revision=2))
        self.assertFalse(recovery_gate(w, a)['recovered'])

    def test_stats_empty_and_scheduled_penalty(self):
        profile = dict(ttft_slo_ms=100, e2el_slo_ms=400)
        self.assertFalse(stats([], 20, profile)['healthy'])
        row = dict(success=True, admitted=True, ttft_ms=90, e2el_ms=395, dispatch_lag_s=.01)
        measured = stats([row]*30, 20, profile)
        self.assertEqual(measured['compliant'], 30)
        self.assertEqual(measured['scheduled_compliant'], 0)

    def test_baseline_gate_and_two_seed_replication(self):
        cases = [dict(seed=s, arm=a, before_healthy=True, low_anchor_reproduced=True,
                      high_anchor_reproduced=True, recovery=dict(recovered=True), goodput=1,
                      rejections=1, completed_slo_violations=0)
                 for s in (309, 310) for a in ('low', 'high', 'adaptive')]
        self.assertEqual(verdict(cases)['status'], 'recovery_replicated')
        cases[-1]['recovery']['recovered'] = False
        self.assertEqual(verdict(cases)['status'], 'recovery_not_replicated')
        cases[0]['low_anchor_reproduced'] = False
        self.assertEqual(verdict(cases)['status'], 'inconclusive_baseline')
        with self.assertRaises(ValueError): verdict(cases[:-1])


if __name__ == '__main__': unittest.main()
