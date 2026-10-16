import asyncio
import copy
import itertools
import json
from pathlib import Path
import subprocess
import sys
import unittest
from coarse_plan import next_step, drive, make_trace, validate


def row(seed, rate, label):
    return dict(seed=seed, rate=rate, classification=label)


class CoarsePlanTest(unittest.TestCase):
    def test_early_high_and_confirmation_order(self):
        history = [row(307, 18, 'low'), row(307, 24, 'high')]
        self.assertEqual(next_step(history), dict(kind='run', seed=308, rate=24))
        history.append(row(308, 24, 'high'))
        self.assertEqual(next_step(history), dict(kind='run', seed=308, rate=18))
        history.append(row(308, 18, 'low'))
        self.assertEqual(next_step(history)['status'], 'candidate_found')

    def test_cap_without_high(self):
        history = [row(307, rate, 'low') for rate in (18, 24, 36, 48)]
        self.assertEqual(next_step(history)['status'], 'inconclusive')
        with self.assertRaises(ValueError):
            next_step(history+[row(307, 60, 'high')])

    def test_no_borrowed_low(self):
        self.assertEqual(next_step([row(307, 18, 'high')])['status'], 'inconclusive')

    def test_ambiguous_not_anchor(self):
        history = [row(307, 18, 'low'), row(307, 24, 'ambiguous'), row(307, 36, 'high')]
        history.append(row(308, 36, 'high'))
        self.assertEqual(next_step(history)['rate'], 18)

    def test_confirmation_failure_stops_immediately(self):
        history = [row(307, 18, 'low'), row(307, 24, 'high'), row(308, 24, 'low')]
        self.assertEqual(next_step(history)['status'], 'inconclusive')
        with self.assertRaises(ValueError):
            next_step(history+[row(308, 18, 'low')])

    def test_identity_and_invalid_label_rejected(self):
        for bad in (row(308, 18, 'low'), row(307, 24, 'low'), row(307, 18, 'error')):
            with self.assertRaises(ValueError):
                next_step([bad])

    def test_all_possible_paths_bounded(self):
        for labels in itertools.product(('low', 'high', 'ambiguous'), repeat=6):
            history = []
            for label in labels:
                action = next_step(history)
                if action['kind'] == 'stop':
                    break
                history.append(row(action['seed'], action['rate'], label))
            self.assertEqual(next_step(history)['kind'], 'stop')
            self.assertLessEqual(len(history), 6)

    def test_driver_exception_no_checkpoint_or_next_launch(self):
        calls, checkpoints, history = [], [], []
        async def fail(seed, rate):
            calls.append((seed, rate))
            raise RuntimeError('backend failed')
        with self.assertRaises(RuntimeError):
            asyncio.run(drive(fail, history, checkpoints.append))
        self.assertEqual(calls, [(307, 18)])
        self.assertEqual(history, [])
        self.assertEqual(checkpoints, [])

    def test_checkpoint_failure_no_next_launch(self):
        calls, history = [], []
        async def run(seed, rate):
            calls.append((seed, rate))
            return row(seed, rate, 'low')
        def fail_checkpoint(rows):
            raise OSError('disk full')
        with self.assertRaises(OSError):
            asyncio.run(drive(run, history, fail_checkpoint))
        self.assertEqual(calls, [(307, 18)])

    def test_successful_drive_checkpoint_prefixes(self):
        checkpoints, history = [], []
        async def run(seed, rate):
            return row(seed, rate, 'low' if rate == 18 else 'high')
        selection = asyncio.run(drive(run, history, lambda rows: checkpoints.append(copy.deepcopy(rows))))
        self.assertEqual(selection['status'], 'candidate_found')
        self.assertEqual([len(c) for c in checkpoints], [1, 2, 3, 4])

    def test_config_trace_and_preview(self):
        folder = Path(__file__).parent
        config = json.loads((folder/'coarse_config.json').read_text())
        validate(config)
        for key, value in [('rates', [18, 24, 36, 60]), ('coarse_seed', 309), ('max_pending_tasks', 256)]:
            bad = {**config, key: value}
            with self.assertRaises(ValueError):
                validate(bad)
        for seed in (307, 308):
            trace = make_trace(seed)
            self.assertEqual(trace, make_trace(seed))
            self.assertTrue(all(0 < r['at'] < 120 for r in trace))
            self.assertLessEqual(len(trace), 10000)
        result = subprocess.run([sys.executable, str(folder/'run_coarse_bracket.py')],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['first_step'], next_step([]))


if __name__ == '__main__':
    unittest.main()
