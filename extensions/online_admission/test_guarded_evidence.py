"""Synthetic recovery phase/telemetry tests; base ledger audit is mocked here."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from guarded_recovery_analysis import analyze_case


class GuardedEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        (self.folder/'fixed').mkdir()
        self.profile = dict(name='balanced', ttft_slo_ms=100, e2el_slo_ms=400)
        self.put('fixed/run_metadata.json', dict(origin=0, duration=260, profile=self.profile))
        self.rows = [dict(success=True, admitted=True, started_at_s=i/2+.01, completed_at_s=i/2+.21,
                          scheduled_at_s=i/2, dispatch_lag_s=.01, ttft_ms=20, e2el_ms=200)
                     for i in range(520)]
        self.samples = [dict(at=i+.01, finished_at=i+.02, metrics=dict(running=1, waiting=0),
                            raw='vllm:num_requests_running 1\nvllm:num_requests_waiting 0\n') for i in range(259)]
        self.lines('fixed/control.jsonl', [])
        mocked = patch('guarded_recovery_analysis.audit_mode', return_value={})
        mocked.start()
        self.addCleanup(mocked.stop)

    def put(self, name, data):
        (self.folder/name).write_text(json.dumps(data), encoding='utf-8')

    def lines(self, name, data):
        (self.folder/name).write_text('\n'.join(json.dumps(r) for r in data), encoding='utf-8')

    def analyze(self):
        self.lines('fixed/requests.jsonl', self.rows)
        self.lines('queue.jsonl', self.samples)
        return analyze_case(self.folder, [], 403, 'low')

    def test_phase_partition_and_low_anchor(self):
        result = self.analyze()
        self.assertEqual([result['phases'][k]['offered'] for k in ('initial', 'guard', 'high', 'after')], [80, 40, 320, 80])
        self.assertEqual(len(result['grid_windows']), 13)
        self.assertTrue(result['before_healthy'] and result['low_anchor_reproduced'])

    def test_scheduled_phase_differs_from_actual_window(self):
        self.rows[79]['scheduled_at_s'] = 39.99
        self.rows[79]['started_at_s'] = 40.01
        result = self.analyze()
        self.assertEqual(result['phases']['initial']['offered'], 80)
        self.assertEqual(result['grid_windows'][1]['offered'], 39)
        self.assertEqual(result['grid_windows'][2]['offered'], 41)

    def test_two_bad_windows_reproduce_high(self):
        for row in self.rows:
            if 60 <= row['scheduled_at_s'] < 100:
                row['e2el_ms'] = 450
        result = self.analyze()
        self.assertTrue(result['high_anchor_reproduced'])
        self.assertFalse(result['low_anchor_reproduced'])

    def test_insufficient_telemetry(self):
        self.samples = self.samples[:199]
        with self.assertRaisesRegex(ValueError, 'coverage'): self.analyze()

    def test_raw_metric_tamper(self):
        self.samples[0]['metrics']['waiting'] = 1
        with self.assertRaisesRegex(ValueError, 'raw metrics'): self.analyze()

    def test_scrape_failure_stops(self):
        self.samples[0]['error'] = 'TimeoutError'
        with self.assertRaisesRegex(ValueError, 'telemetry failure'): self.analyze()

    def test_long_gap_rejected(self):
        self.samples = self.samples[:100]+self.samples[104:]
        with self.assertRaisesRegex(ValueError, 'gap'): self.analyze()


if __name__ == '__main__': unittest.main()


