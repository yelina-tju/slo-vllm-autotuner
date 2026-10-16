import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from run_static_endpoints import plan


class StaticPlanTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        manifest = dict(config=dict(pairs=[dict(seed=202), dict(seed=203)],
                                    phases=[dict(seconds=1)]), profile={}, profile_sha256='fixture')
        (self.root/'batch_manifest.json').write_text(json.dumps(manifest))
        for seed in (202, 203):
            folder = self.root/f'seed{seed}'
            folder.mkdir()
            self.trace(seed, [dict(at=.1, prompt_seed=seed)])
        # Isolate planning checks; full real reference audit is tested separately.
        mock = patch('run_static_endpoints.audit_batch', return_value={'status': 'passed'})
        self.audit = mock.start()
        self.addCleanup(mock.stop)

    def trace(self, seed, rows):
        folder = self.root/f'seed{seed}'
        (folder/'trace.json').write_text(json.dumps(rows))
        (folder/'trace_hash.json').write_text(json.dumps(dict(
            sha256=hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest())))

    def test_exact_endpoint_order_and_no_output_side_effect(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        result = plan(self.root)
        self.assertEqual([(c['seed'], c['fixed_rate']) for c in result['cases']],
                         [(202, 3), (202, 6), (203, 6), (203, 3)])
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))
        self.audit.assert_called_once_with(self.root)

    def test_changed_trace_rejected(self):
        (self.root/'seed202/trace.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'trace changed'):
            plan(self.root)

    def test_out_of_bounds_time_rejected_even_with_valid_hash(self):
        self.trace(202, [dict(at=2, prompt_seed=1)])
        with self.assertRaisesRegex(ValueError, 'arrival times'):
            plan(self.root)

    def test_invalid_reference_audit_blocks_plan(self):
        self.audit.side_effect = ValueError('reference audit failed')
        with self.assertRaisesRegex(ValueError, 'reference audit failed'):
            plan(self.root)


if __name__ == '__main__':
    unittest.main()
