"""The documented CPU replay must work against the current controller contract."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ReplayEntrypointTest(unittest.TestCase):
    def test_fresh_evidence_replay_and_no_overwrite(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'replay.json'
            command = [sys.executable, str(root / 'scripts/replay_controller.py'), '--output', str(output)]
            run = subprocess.run(command, cwd=root, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr.decode(errors='replace'))
            original = output.read_bytes()
            result = json.loads(original)
            self.assertEqual(result['transition_sequence'], ['switch', 'rollback', 'switch'])
            repeated = next(d for d in result['decisions'] if d['timestamp_s'] == 155)
            self.assertNotEqual(repeated['action'], 'rollback')
            rerun = subprocess.run(command, cwd=root, capture_output=True, timeout=30)
            self.assertNotEqual(rerun.returncode, 0)
            self.assertEqual(output.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
