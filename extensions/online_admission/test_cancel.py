import unittest
from types import SimpleNamespace
from probe_cancel import parse_metrics, verdict, tagged_abort_lines


class CancelTest(unittest.TestCase):
    def test_abort_event_matches_exact_tag(self):
        raw = 'Request cmpl-case-10-0 aborted.\nRequest cmpl-case-1-0 aborted.\nRequest cmpl-case-1-0 received.'
        self.assertEqual(tagged_abort_lines(raw, 'case-1'), ['Request cmpl-case-1-0 aborted.'])

    def test_metrics_required_and_abort_label(self):
        raw = '\n'.join(['vllm:num_requests_running{engine="0"} 1',
                         'vllm:num_requests_waiting 0', 'vllm:generation_tokens_total 123',
                         'vllm:request_success_total{finished_reason="abort"} 2',
                         'vllm:request_success_total{finished_reason="length"} 3'])
        self.assertEqual(parse_metrics(raw)['abort'], 2)
        with self.assertRaises(ValueError):
            parse_metrics('vllm:num_requests_running 0')

    def test_idle_alone_is_not_abort_proof(self):
        before = dict(running=0, waiting=0, tokens=0, abort=0, length=0)
        after = dict(running=0, waiting=0, tokens=2048, abort=0, length=1)
        checks = verdict(before, after, [dict(metrics=dict(running=1))],
                         dict(error='TimeoutError', outcome='timeout', ttft_ms=10),
                         [dict(applied=True, decision=SimpleNamespace(reason='request_timeout'))], True)
        self.assertFalse(checks['abort_increment'])
        self.assertFalse(checks['no_length_completion'])
        self.assertFalse(checks['token_work_below_full'])
