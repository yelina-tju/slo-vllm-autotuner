"""Synthetic provenance tamper tests; actual latency reconstruction tested separately."""
import hashlib
import json
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch
from audit_recovery import audit, sha
from recovery_plan import CONFIG, plan, make_trace, case_config
from recovery_analysis import verdict


class RecoveryAuditTest(unittest.TestCase):
    def put(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf-8')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.folder, self.snapshot, self.prior = [root/name for name in ('results', 'source', 'prior')]
        for folder in (self.folder, self.snapshot, self.prior): folder.mkdir()
        (self.snapshot/'runner.py').write_text('# fixture')
        self.put(self.prior/'report.json', dict(selection=dict(status='candidate_found', low_rate=24, high_rate=48)))
        self.manifest = dict(config=CONFIG, source_files={'runner.py': sha(self.snapshot/'runner.py')},
                             profile={'name': 'balanced'}, profile_sha256='profile', frozen_dependencies={'executor.py': 'frozen'},
                             calibration_report_sha256=sha(self.prior/'report.json'))
        self.put(self.folder/'manifest.json', self.manifest)
        self.put(self.prior/'manifest.json', self.manifest)
        backend = dict(command=['vllm', '--port', '8031'], sources=self.manifest['source_files'], model_config_sha256='model')
        self.put(self.prior/'seed307-static24/backend/manifest.json', backend)
        for seed in (309, 310):
            trace = make_trace(seed)
            self.put(self.folder/f'trace-{seed}.json', trace)
            self.put(self.folder/f'trace-{seed}-hash.json', dict(sha256=hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest()))
        self.records = []
        for item in plan(CONFIG):
            seed, arm = item['seed'], item['arm']
            case = self.folder/f'seed{seed}-{arm}'
            config, mode = case_config(CONFIG, seed, arm)
            self.put(case/mode/'run_metadata.json', dict(config=config, profile=self.manifest['profile']))
            self.put(case/'backend/manifest.json', backend)
            self.put(case/'backend/cleanup.json', dict(stopped=True))
            self.put(case/'backend/warmup.json', [dict(token=True, done=True, status=200)]*4)
            record = dict(seed=seed, arm=arm, before_healthy=True, low_anchor_reproduced=True,
                          high_anchor_reproduced=True, recovery=dict(recovered=True), goodput=1,
                          rejections=1, completed_slo_violations=0, accounting_requests=2)
            self.put(case/'analysis.json', record)
            self.records.append(record)
            self.put(self.folder/f'checkpoint-{len(self.records):02d}.json', dict(completed=self.records))
        self.report = dict(status='passed', completed=self.records, verdict=verdict(self.records))
        self.put(self.folder/'report.json', self.report)

    def run_audit(self, allow_partial=False):
        def reconstruct(folder, trace, seed, arm):
            return next(r for r in self.records if (r['seed'], r['arm']) == (seed, arm))
        with patch('audit_recovery.analyze_case', side_effect=reconstruct):
            return audit(self.folder, self.snapshot, self.prior, allow_partial)

    def make_partial(self):
        old = self.folder
        self.folder = old.parent/'partial'
        self.folder.mkdir()
        for name in ('manifest.json', 'trace-309.json', 'trace-309-hash.json',
                     'trace-310.json', 'trace-310-hash.json', 'checkpoint-01.json', 'checkpoint-02.json'):
            shutil.copyfile(old/name, self.folder/name)
        for name in ('seed309-low', 'seed309-high'):
            shutil.copytree(old/name, self.folder/name)
        (self.folder/'seed309-adaptive').mkdir()
        self.put(self.folder/'report.json', dict(status='failed', completed=self.records[:2],
                 error="OSError(98, 'Address already in use')"))

    def test_partial_requires_explicit_opt_in_and_never_claims_recovery(self):
        self.make_partial()
        with self.assertRaisesRegex(ValueError, 'incomplete'): self.run_audit()
        result = self.run_audit(True)
        self.assertEqual(result['status'], 'completed_prefix_verified')
        self.assertEqual(result['verdict']['status'], 'not_evaluated_incomplete_batch')
        self.assertEqual(len(result['verdict']['remaining_cases']), 4)

    def test_partial_rejects_any_unreviewed_failed_case_artifact(self):
        self.make_partial()
        self.put(self.folder/'seed309-adaptive/unexpected.json', {})
        with self.assertRaisesRegex(ValueError, 'prelaunch-empty'): self.run_audit(True)

    def test_valid(self):
        self.assertEqual(self.run_audit()['verdict']['status'], 'recovery_replicated')

    def test_source_tamper(self):
        (self.snapshot/'runner.py').write_text('# different')
        with self.assertRaisesRegex(ValueError, 'source hash'): self.run_audit()

    def test_calibration_tamper(self):
        self.put(self.prior/'report.json', {})
        with self.assertRaisesRegex(ValueError, 'calibration changed'): self.run_audit()

    def test_checkpoint_tamper(self):
        self.put(self.folder/'checkpoint-01.json', {})
        with self.assertRaisesRegex(ValueError, 'checkpoint mismatch'): self.run_audit()

    def test_failed_cleanup(self):
        self.put(self.folder/'seed309-low/backend/cleanup.json', dict(stopped=False))
        with self.assertRaisesRegex(ValueError, 'cleanup failed'): self.run_audit()

    def test_extra_case(self):
        (self.folder/'seed311-adaptive').mkdir()
        with self.assertRaisesRegex(ValueError, 'unreported case'): self.run_audit()

    def test_verdict_tamper(self):
        self.report['verdict']['status'] = 'overclaimed'
        self.put(self.folder/'report.json', self.report)
        with self.assertRaisesRegex(ValueError, 'verdict mismatch'): self.run_audit()


if __name__ == '__main__': unittest.main()
