import copy
import unittest
from heldout_protocol import CONFIG, case_config
from recovery_plan import CONFIG as DEVELOPMENT


class HeldoutProtocolTest(unittest.TestCase):
    def test_frozen_settings_unchanged(self):
        for key in DEVELOPMENT:
            if key not in ('protocol', 'orders'):
                self.assertEqual(CONFIG[key], DEVELOPMENT[key])

    def test_case_modes_and_isolation(self):
        for seed in (401, 402):
            for arm in ('low', 'high', 'adaptive'):
                cfg, mode = case_config(CONFIG, seed, arm)
                self.assertEqual(cfg['seed'], seed)
                self.assertEqual(mode, 'adaptive_deadline' if arm == 'adaptive' else 'fixed')
                if arm != 'adaptive':
                    self.assertEqual(cfg['fixed_rate'], 24 if arm == 'low' else 48)
                else:
                    self.assertNotIn('fixed_rate', cfg)
                cfg['feedback']['initial'] = 999
                self.assertEqual(CONFIG['feedback']['initial'], 48)

    def test_retuning_or_old_seed_rejected(self):
        bad = copy.deepcopy(CONFIG)
        bad['feedback']['confirmations'] = 1
        for cfg, seed, arm in ((bad, 401, 'adaptive'), (CONFIG, 309, 'low'), (CONFIG, 401, 'oracle')):
            with self.assertRaises(ValueError):
                case_config(cfg, seed, arm)


if __name__ == '__main__':
    unittest.main()
