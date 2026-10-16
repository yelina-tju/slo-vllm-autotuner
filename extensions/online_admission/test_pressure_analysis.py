import copy
import json
from pathlib import Path
import unittest
from pressure_analysis import validate, make_trace, queue_metrics, max_inflight, classify, select_pair


class PressureAnalysisTest(unittest.TestCase):
    def test_frozen_plan_and_trace(self):
        cfg = json.loads(Path(__file__).with_name('pressure_config.json').read_text())
        validate(cfg)
        bad = copy.deepcopy(cfg)
        bad['orders'][0]['rates'][-1] = 12
        with self.assertRaises(ValueError):
            validate(bad)
        for seed in (303, 304):
            rows = make_trace(seed)
            self.assertEqual(rows, make_trace(seed))
            self.assertTrue(all(0 <= r['at'] < 120 for r in rows))
            self.assertLess(len(rows), 10000)

    def test_raw_queue_metrics(self):
        raw = '# comment\nvllm:num_requests_running{engine="0"} 2\nvllm:num_requests_waiting{engine="0"} 0\n'
        self.assertEqual(queue_metrics(raw), dict(running=2, waiting=0))
        for bad in ('', raw.replace(' 2', ' NaN'), raw.replace(' 2', ' -1')):
            with self.assertRaises(ValueError):
                queue_metrics(bad)

    def test_low_high_ambiguous_boundaries(self):
        self.assertEqual(classify([1]*6, 1, .01), 'low')
        self.assertEqual(classify([1]*6, 1, .02), 'ambiguous')
        self.assertEqual(classify([1.01]+[.9]*5, 1, .01), 'ambiguous')
        self.assertEqual(classify([1.01]*2+[.9]*4, 1.01, .02), 'high')
        with self.assertRaises(ValueError):
            classify([.9]*5, .9, 0)
        with self.assertRaises(ValueError):
            classify([.9]*6, float('nan'), 0)

    def cases(self):
        return [dict(seed=s, rate=r, classification='low' if r < 9 else 'high')
                for s in (303, 304) for r in (3, 6, 9)]

    def test_selection_requires_replication_and_preserves_inconclusive(self):
        cases = self.cases()
        selected = select_pair(cases)
        self.assertEqual((selected['low_rate'], selected['high_rate']), (6, 9))
        cases[-1]['classification'] = 'ambiguous'
        self.assertEqual(select_pair(cases)['status'], 'inconclusive')
        with self.assertRaises(ValueError):
            select_pair(cases[:-1])
        cases[-1] = cases[0]
        with self.assertRaises(ValueError):
            select_pair(cases)

    def test_lower_anchor_selected_when_middle_ambiguous(self):
        cases = self.cases()
        for c in cases:
            if c['rate'] == 6:
                c['classification'] = 'ambiguous'
        self.assertEqual(select_pair(cases)['low_rate'], 3)

    def test_client_inflight_is_not_offered_count(self):
        rows = [dict(admitted=True, started_at_s=0, completed_at_s=2),
                dict(admitted=True, started_at_s=1, completed_at_s=3),
                dict(admitted=False, started_at_s=1, completed_at_s=1)]
        self.assertEqual(max_inflight(rows), 2)


if __name__ == '__main__':
    unittest.main()
