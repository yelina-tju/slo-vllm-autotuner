"""Environment integration checks; imports HTTP driver but never starts GPU."""
import unittest
from recovery_plan import CONFIG, make_trace, case_config
from run_pilot import trace
from feedback import Config


class RecoveryIntegrationTest(unittest.TestCase):
    def test_trace_matches_real_driver(self):
        for seed in (309, 310):
            arrivals, duration = trace({**CONFIG, 'seed': seed})
            self.assertEqual(arrivals, make_trace(seed))
            self.assertEqual(duration, 240)

    def test_adverse_config_is_evaluation_only(self):
        import json
        from pathlib import Path
        historical = json.loads(Path(__file__).with_name('coarse_config.json').read_text())
        self.assertEqual(historical['feedback']['maximum'], 6)
        for arm in ('low', 'high', 'adaptive'):
            config, mode = case_config(CONFIG, 309, arm)
            self.assertEqual(Config(**config['feedback']).initial, 48)
            self.assertEqual(mode == 'fixed', arm != 'adaptive')


if __name__ == '__main__': unittest.main()
