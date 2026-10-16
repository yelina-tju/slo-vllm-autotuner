"""Synthetic linked-provenance tests; prefix audit and raw math tested separately."""
import json
import shutil
import unittest
from unittest.mock import patch
from audit_recovery_continuation import audit
from audit_recovery import read, sha
from recovery_plan import CONFIG, plan
from recovery_analysis import verdict


class LinkedAuditTest(unittest.TestCase):
    def setUp(self):
        from test_recovery_audit import RecoveryAuditTest
        self.fixture = RecoveryAuditTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.prefix = self.fixture.folder
        self.folder = self.prefix.parent/'continuation'
        self.folder.mkdir()
        self.context = dict(prefix_cases=self.fixture.records[:2], remaining=plan(CONFIG)[2:],
                            link=dict(trace_file_sha256={str(s): sha(self.prefix/f'trace-{s}.json') for s in (309, 310)}))
        self.traces = {s: read(self.prefix/f'trace-{s}.json') for s in (309, 310)}
        manifest = read(self.prefix/'manifest.json')
        manifest['continuation'] = self.context['link']
        self.put('manifest.json', manifest)
        for seed in (309, 310):
            for suffix in ('.json', '-hash.json'):
                shutil.copyfile(self.prefix/f'trace-{seed}{suffix}', self.folder/f'trace-{seed}{suffix}')
        records = self.fixture.records[2:]
        for i, record in enumerate(records, 1):
            name = f'seed{record["seed"]}-{record["arm"]}'
            shutil.copytree(self.prefix/name, self.folder/name)
            self.put(f'checkpoint-{i:02d}.json', dict(completed=records[:i]))
        self.put('report.json', dict(status='passed', completed=records, verdict=verdict(self.fixture.records)))

    def put(self, name, data):
        self.fixture.put(self.folder/name, data)

    def run_audit(self):
        def reconstruct(folder, trace, seed, arm):
            return next(r for r in self.fixture.records if (r['seed'], r['arm']) == (seed, arm))
        with patch('audit_recovery_continuation.prepare', return_value=(self.context, self.traces)), \
             patch('audit_recovery_continuation.analyze_case', side_effect=reconstruct):
            return audit(self.folder, self.fixture.snapshot, self.prefix, self.fixture.snapshot, self.fixture.prior)

    def test_valid_link(self):
        result = self.run_audit()
        self.assertEqual(result['new_cases'], 4)
        self.assertEqual(result['preserved_cases'], 2)
        self.assertEqual(result['prefix_batch_status'], 'failed_preserved')

    def test_link_tamper(self):
        manifest = read(self.folder/'manifest.json')
        manifest['continuation']['trace_file_sha256']['309'] = 'tampered'
        self.put('manifest.json', manifest)
        with self.assertRaisesRegex(ValueError, 'link/config'): self.run_audit()

    def test_trace_tamper(self):
        self.put('trace-309.json', [])
        with self.assertRaisesRegex(ValueError, 'trace not reused'): self.run_audit()

    def test_repeated_control_rejected(self):
        report = read(self.folder/'report.json')
        report['completed'][0] = self.fixture.records[0]
        self.put('report.json', report)
        with self.assertRaisesRegex(ValueError, 'repeated or reordered'): self.run_audit()

    def test_failed_continuation_not_accepted(self):
        report = read(self.folder/'report.json')
        report['status'] = 'failed'
        self.put('report.json', report)
        with self.assertRaisesRegex(ValueError, 'incomplete'): self.run_audit()

    def test_checkpoint_tamper(self):
        self.put('checkpoint-01.json', {})
        with self.assertRaisesRegex(ValueError, 'checkpoint'): self.run_audit()

    def test_verdict_tamper(self):
        report = read(self.folder/'report.json')
        report['verdict']['status'] = 'overclaimed'
        self.put('report.json', report)
        with self.assertRaisesRegex(ValueError, 'verdict'): self.run_audit()


if __name__ == '__main__': unittest.main()
