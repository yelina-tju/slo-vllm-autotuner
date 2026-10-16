import json
from pathlib import Path
import tempfile
import unittest
from audit_cancel import audit, metric_file, exact_abort_events


class AuditCancelTest(unittest.TestCase):
    def test_tag_event_is_not_a_prefix_match(self):
        self.assertEqual(exact_abort_events('Request cmpl-case-10-0 aborted.', 'case-1'), [])
        self.assertEqual(len(exact_abort_events('Request cmpl-case-1-0 aborted.', 'case-1')), 1)
    def test_failed_protocol_can_have_consistent_evidence(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            def raw(label, tokens, length, running=0):
                values = dict(running=running, waiting=0, tokens=tokens, abort=0, length=length)
                (folder/f'metrics-0001-{label}.txt').write_text(
                    f'vllm:num_requests_running {running}\nvllm:num_requests_waiting 0\n'
                    f'vllm:generation_tokens_total {tokens}\n'
                    'vllm:request_success_total{finished_reason="abort"} 0\n'
                    f'vllm:request_success_total{{finished_reason="length"}} {length}\n')
                return values
            def put(filename, obj):
                (folder/filename).write_text(json.dumps(obj))
            raw('control-before', 0, 0)
            raw('control-after', 2048, 1)
            put('full-length-control.json', dict(result=dict(success=True, e2el_ms=8000)))
            for i in (1, 2):
                before = raw(f'{i}-before', 2048*i, i)
                after = raw(f'{i}-after', 2048*i+350, i)
                raw(f'{i}-during', 2048*i+100, i, 1)
                put(f'case-{i}.json', dict(before=dict(metrics=before), after=dict(metrics=after, at=4),
                    client_result=dict(error='TimeoutError', outcome='timeout', ttft_ms=10),
                    post=[dict(at=2, metrics=after), dict(at=4, metrics=after)], client_finished_at=1,
                    controls=[dict(applied=True, decision=dict(reason='request_timeout', rate=2.1))],
                    checks=dict(gate_released=True, healthy=True, abort_increment=False),
                    recovery=dict(success=True), passed=False, first_idle_observed_after_client_s=1,
                    plateau_confirmed_after_client_s=3))
            put('cleanup.json', dict(stopped=True))
            put('report.json', dict(status='failed'))
            result = audit(folder)
            self.assertEqual(result['evidence_consistency'], 'passed')
            self.assertEqual(result['original_protocol_status'], 'failed')
            put('report.json', dict(status='passed'))
            with self.assertRaisesRegex(ValueError, 'verdict inconsistent'):
                audit(folder)

    def test_missing_metrics_not_zero(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)/'metrics.txt'
            path.write_text('vllm:num_requests_running 0\n')
            with self.assertRaises(ValueError):
                metric_file(path)
