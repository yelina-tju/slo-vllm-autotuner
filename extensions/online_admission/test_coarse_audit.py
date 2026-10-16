"""Synthetic provenance tamper tests; per-request math is tested separately."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from audit_coarse_bracket import audit, sha
from coarse_plan import make_trace, next_step


class CoarseAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.folder, self.snapshot, self.reference = [root/name for name in ('results', 'snapshot', 'reference')]
        for folder in (self.folder, self.snapshot, self.reference):
            folder.mkdir()
        self.config = json.loads(Path(__file__).with_name('coarse_config.json').read_text())
        self.put(self.snapshot/'coarse_config.json', self.config)
        (self.snapshot/'runner.py').write_text('# synthetic fixture\n')
        self.manifest = dict(config=self.config, config_sha256=sha(self.snapshot/'coarse_config.json'),
                             source_files={'runner.py': sha(self.snapshot/'runner.py')},
                             profile={'name': 'balanced'}, profile_sha256='profile', frozen_dependencies={'executor.py': 'frozen'})
        self.put(self.folder/'manifest.json', self.manifest)
        self.put(self.reference/'manifest.json', self.manifest)
        self.backend = dict(command=['vllm', '--port', '8029'], sources=self.manifest['source_files'], model_config_sha256='model')
        self.put(self.reference/'seed202-static3/backend/manifest.json', self.backend)
        for seed in (307, 308):
            trace = make_trace(seed)
            self.put(self.folder/f'trace-{seed}.json', trace)
            self.put(self.folder/f'trace-{seed}-hash.json', dict(sha256=hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest()))
        self.records = []
        for seed, rate, label in ((307, 18, 'low'), (307, 24, 'high'), (308, 24, 'high'), (308, 18, 'low')):
            record = dict(seed=seed, rate=rate, classification=label, accounting_requests=10, completed_slo_violations=0)
            case = self.folder/f'seed{seed}-static{rate}'
            self.put(case/'fixed/run_metadata.json', dict(config={**self.config, 'seed': seed, 'fixed_rate': rate}, profile=self.manifest['profile']))
            self.put(case/'backend/manifest.json', self.backend)
            self.put(case/'backend/cleanup.json', dict(stopped=True))
            self.put(case/'backend/warmup.json', [dict(token=True, done=True, status=200)]*4)
            self.put(case/'analysis.json', record)
            self.records.append(record)
            self.put(self.folder/f'checkpoint-{len(self.records):02d}.json', dict(completed=self.records, next_step=next_step(self.records)))
        self.report = dict(status='passed', completed=self.records, selection=next_step(self.records))
        self.put(self.folder/'report.json', self.report)

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def run_audit(self):
        def reconstructed(folder, trace, seed, rate):
            return next(r for r in self.records if (r['seed'], r['rate']) == (seed, rate))
        with patch('audit_coarse_bracket.analyze_case', side_effect=reconstructed):
            return audit(self.folder, self.snapshot, self.reference)

    def test_valid_sequential_report(self):
        self.assertEqual(self.run_audit()['cases_executed'], 4)

    def test_source_tamper(self):
        (self.snapshot/'runner.py').write_text('# tampered')
        with self.assertRaisesRegex(ValueError, 'source hash'):
            self.run_audit()

    def test_trace_tamper(self):
        self.put(self.folder/'trace-307.json', [])
        with self.assertRaisesRegex(ValueError, 'trace mismatch'):
            self.run_audit()

    def test_checkpoint_tamper(self):
        self.put(self.folder/'checkpoint-01.json', {})
        with self.assertRaisesRegex(ValueError, 'checkpoint mismatch'):
            self.run_audit()

    def test_unreported_case_rejected(self):
        (self.folder/'seed307-static36').mkdir()
        with self.assertRaisesRegex(ValueError, 'unreported'):
            self.run_audit()

    def test_wrong_order_rejected(self):
        self.report['completed'] = list(reversed(self.records))
        self.put(self.folder/'report.json', self.report)
        with self.assertRaisesRegex(ValueError, 'off-plan'):
            self.run_audit()

    def test_cleanup_failure_rejected(self):
        self.put(self.folder/'seed307-static18/backend/cleanup.json', dict(stopped=False))
        with self.assertRaisesRegex(ValueError, 'cleanup failed'):
            self.run_audit()

    def test_selection_tamper(self):
        self.report['selection']['low_rate'] = 24
        self.put(self.folder/'report.json', self.report)
        with self.assertRaisesRegex(ValueError, 'terminal selection'):
            self.run_audit()


if __name__ == '__main__':
    unittest.main()
