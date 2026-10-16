"""Synthetic provenance tests, not model performance measurements."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from audit_heldout import audit_batch
from heldout_protocol import CONFIG, case_config
from heldout_plan import plan, make_trace
from heldout_analysis import verdict


class HeldoutAuditTest(unittest.TestCase):
    def put(self, name, value):
        path = self.folder/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.traces = {s: make_trace(s) for s in (401, 402)}
        self.frozen = dict(config=CONFIG, source_files={'runner.py': 'hash'}, profile={'name': 'balanced'},
                           profile_sha256='profile', frozen_dependencies={}, calibration_report_sha256='prior',
                           trace_sha256={str(s): hashlib.sha256(json.dumps(t, sort_keys=True).encode()).hexdigest()
                                         for s, t in self.traces.items()},
                           backend=dict(command=['vllm', '--port', '8031'], model_config_sha256='model'))
        self.put('freeze.json', self.frozen)
        self.put('frozen-protocol.json', self.frozen)
        self.put('manifest.json', {**self.frozen, 'frozen_protocol': self.frozen})
        for s, trace in self.traces.items():
            self.put(f'trace-{s}.json', trace)
            self.put(f'trace-{s}-hash.json', dict(sha256=self.frozen['trace_sha256'][str(s)]))
        self.records = []
        for item in plan():
            seed, arm = item['seed'], item['arm']
            name = f'seed{seed}-{arm}'
            cfg, mode = case_config(CONFIG, seed, arm)
            self.put(f'{name}/{mode}/run_metadata.json', dict(config=cfg, profile=self.frozen['profile']))
            self.put(f'{name}/backend/manifest.json', {**self.frozen['backend'], 'sources': self.frozen['source_files']})
            self.put(f'{name}/backend/warmup.json', [dict(token=True, done=True, status=200)]*4)
            self.put(f'{name}/backend/cleanup.json', dict(stopped=True))
            r = dict(seed=seed, arm=arm, before_healthy=True, low_anchor_reproduced=True,
                     high_anchor_reproduced=True, recovery=dict(recovered=True), goodput=1,
                     rejections=1, completed_slo_violations=0, accounting_requests=len(self.traces[seed]))
            self.records.append(r)
            self.put(f'{name}/analysis.json', r)
            self.put(f'checkpoint-{len(self.records):02d}.json', dict(completed=self.records))
        self.report = dict(status='passed', completed=self.records, verdict=verdict(self.records))
        self.put('report.json', self.report)

    def run_audit(self):
        def reconstruct(folder, trace, seed, arm):
            return next(r for r in self.records if (r['seed'], r['arm']) == (seed, arm))
        with patch('audit_heldout.prepare', return_value=(self.frozen, self.traces)), \
             patch('audit_heldout.analyze_case', side_effect=reconstruct):
            return audit_batch(self.folder, self.folder, None, self.folder/'freeze.json')

    def test_valid(self):
        self.assertEqual(self.run_audit()['offered_records'], 72402)

    def test_freeze_tampering(self):
        self.put('frozen-protocol.json', {})
        with self.assertRaisesRegex(ValueError, 'protocol'): self.run_audit()

    def test_trace_tampering(self):
        self.put('trace-401.json', [])
        with self.assertRaisesRegex(ValueError, 'trace changed'): self.run_audit()

    def test_failed_report(self):
        self.report['status'] = 'failed'
        self.put('report.json', self.report)
        with self.assertRaisesRegex(ValueError, 'incomplete'): self.run_audit()

    def test_checkpoint_tampering(self):
        self.put('checkpoint-01.json', {})
        with self.assertRaisesRegex(ValueError, 'checkpoint'): self.run_audit()

    def test_cleanup_failure(self):
        self.put('seed401-low/backend/cleanup.json', dict(stopped=False))
        with self.assertRaisesRegex(ValueError, 'cleanup'): self.run_audit()

    def test_unreported_extra_case(self):
        (self.folder/'seed403-low').mkdir()
        with self.assertRaisesRegex(ValueError, 'unexpected case'): self.run_audit()

    def test_verdict_tampering(self):
        self.report['verdict']['status'] = 'superior'
        self.put('report.json', self.report)
        with self.assertRaisesRegex(ValueError, 'verdict'): self.run_audit()


if __name__ == '__main__':
    unittest.main()
