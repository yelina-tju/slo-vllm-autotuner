"""Isolate telemetry/selection gates; base request audit is mocked, not re-proved."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pressure_analysis import analyze_case


class PressureEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        (self.folder/'fixed').mkdir()
        meta = dict(origin=0, duration=120, config=dict(fixed_rate=3),
                    profile=dict(name='balanced', ttft_slo_ms=100, e2el_slo_ms=400))
        (self.folder/'fixed/run_metadata.json').write_text(json.dumps(meta))
        self.lines('fixed/requests.jsonl', [dict(admitted=True, success=True,
            started_at_s=.2, completed_at_s=.4, ttft_ms=50, e2el_ms=200)])
        self.controls = [dict(window=dict(classes=dict(balanced=dict(
            completed=30, failed=0, ttft_ratio=.5, e2e_ratio=.5)))) for _ in range(6)]
        self.lines('fixed/control.jsonl', self.controls)
        self.samples = [dict(at=.2+i, finished_at=.21+i,
            raw='vllm:num_requests_running 1\nvllm:num_requests_waiting 0\n',
            metrics=dict(running=1, waiting=0)) for i in range(118)]
        self.lines('queue.jsonl', self.samples)
        mocked = patch('pressure_analysis.audit_mode', return_value=dict(completed_slo_violations=0))
        mocked.start()
        self.addCleanup(mocked.stop)

    def lines(self, path, rows):
        (self.folder/path).write_text('\n'.join(json.dumps(r) for r in rows))

    def analyze(self):
        return analyze_case(self.folder, [], 303, 3)

    def test_complete_telemetry(self):
        result = self.analyze()
        self.assertEqual(result['classification'], 'low')
        self.assertEqual(result['telemetry_samples'], 118)
        self.assertEqual(result['peak_client_inflight'], 1)

    def test_parsed_metric_tampering(self):
        self.samples[0]['metrics']['waiting'] = 5
        self.lines('queue.jsonl', self.samples)
        with self.assertRaisesRegex(ValueError, 'reconstruction'):
            self.analyze()

    def test_scrape_failure_is_not_zero_queue(self):
        self.samples[0]['error'] = 'TimeoutError'
        self.lines('queue.jsonl', self.samples)
        with self.assertRaisesRegex(ValueError, 'telemetry failed'):
            self.analyze()

    def test_coverage_floor(self):
        self.lines('queue.jsonl', self.samples[:99])
        with self.assertRaisesRegex(ValueError, 'insufficient queue'):
            self.analyze()

    def test_large_sampling_gap(self):
        self.lines('queue.jsonl', self.samples[:50]+self.samples[54:])
        with self.assertRaisesRegex(ValueError, 'telemetry gap'):
            self.analyze()

    def test_slow_scrape_rejected(self):
        self.samples[0]['finished_at'] = 1
        self.lines('queue.jsonl', self.samples)
        with self.assertRaisesRegex(ValueError, 'slow telemetry'):
            self.analyze()

    def test_under_sampled_latency_is_not_low(self):
        self.controls[0]['window']['classes']['balanced']['completed'] = 29
        self.lines('fixed/control.jsonl', self.controls)
        with self.assertRaisesRegex(ValueError, 'insufficient/failed'):
            self.analyze()


if __name__ == '__main__':
    unittest.main()
