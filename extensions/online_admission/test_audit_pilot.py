import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from audit_pilot import audit


class AuditTest(unittest.TestCase):
    def fixture(self, root):
        trace = [dict(at=1)]
        manifest = dict(trace_sha256=hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest(),
                        config=dict(phases=[dict(seconds=10)], feedback=dict(minimum=1, maximum=6, initial=3)),
                        profile=dict(ttft_slo_ms=100, e2el_slo_ms=400))
        for name, value in [('trace.json', trace), ('manifest.json', manifest),
                            ('report.json', dict(status='passed', owned_group_stopped=True))]:
            (root/name).write_text(json.dumps(value))
        for mode in ('fixed', 'adaptive'):
            folder = root/mode
            folder.mkdir()
            row = dict(trace_id=0, request_id=1, scheduled_at_s=1, dispatch_lag_s=0,
                       success=True, admitted=True, status=200, outcome='success', ttft_ms=20, e2el_ms=100)
            control = dict(window=dict(start=0, end=10, classes={}), audit=dict(offered=1),
                           applied=None, decision=None, rate=3)
            summary = dict(requests=1, statuses={'200': 1}, service_slo_compliant=1,
                           scheduled_slo_compliant=1, service_goodput=.1, scheduled_goodput=.1, transitions=0)
            (folder/'requests.jsonl').write_text(json.dumps(row)+'\n')
            (folder/'control.jsonl').write_text(json.dumps(control)+'\n')
            (folder/'summary.json').write_text(json.dumps(summary))

    def test_valid_and_duplicate_request(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            self.assertEqual(audit(root)['accounting_audit'], 'passed')
            path = root/'adaptive/requests.jsonl'
            path.write_text(path.read_text()*2)
            with self.assertRaisesRegex(ValueError, 'missing/duplicate'):
                audit(root)

    def test_trace_corruption_and_unclean_exit(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            (root/'report.json').write_text(json.dumps(dict(status='passed', owned_group_stopped=False)))
            with self.assertRaisesRegex(ValueError, 'cleanup'):
                audit(root)
            (root/'trace.json').write_text('[]')
            with self.assertRaisesRegex(ValueError, 'hash'):
                audit(root)
