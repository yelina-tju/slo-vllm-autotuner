import copy
import json
from pathlib import Path
import unittest
from pressure_analysis import validate, protocol_spec, make_trace, select_pair


class PressureExpansionTest(unittest.TestCase):
    def config(self):
        return json.loads(Path(__file__).with_name('pressure_expanded_config.json').read_text())

    def test_both_protocols_remain_valid(self):
        validate(self.config())
        validate(json.loads(Path(__file__).with_name('pressure_config.json').read_text()))
        self.assertEqual(protocol_spec(self.config()), ((305, 306), (6, 12, 18), 36))

    def test_reject_unregistered_expansion(self):
        for key, value in [('protocol', 'anything'), ('phases', [dict(seconds=120, rps=72)])]:
            cfg = self.config()
            cfg[key] = value
            with self.assertRaises(ValueError):
                validate(cfg)
        cfg = self.config()
        cfg['orders'][0]['rates'][-1] = 36
        with self.assertRaises(ValueError):
            validate(cfg)

    def test_trace_reproducible_and_bounded(self):
        for seed in (305, 306):
            rows = make_trace(seed, 36)
            self.assertEqual(rows, make_trace(seed, 36))
            self.assertLess(len(rows), 10000)
            self.assertTrue(all(0 <= r['at'] < 120 for r in rows))
        with self.assertRaises(ValueError):
            make_trace(305, 72)

    def test_new_selection_cannot_mix_old_seeds(self):
        cases = [dict(seed=s, rate=r, classification='low' if r == 6 else 'high')
                 for s in (305, 306) for r in (6, 12, 18)]
        selection = select_pair(cases, (305, 306), (6, 12, 18))
        self.assertEqual((selection['low_rate'], selection['high_rate']), (6, 12))
        with self.assertRaises(ValueError):
            select_pair(cases)
