"""Publication boundary regression checks, independent of raw experiment files."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publication_files import content_issues, public_files


class PublicationTest(unittest.TestCase):
    def test_extension_assets_and_summary_included_raw_and_credentials_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            included = ['extensions/online_admission/feedback.py',
                        'docs/assets/formulas/example.svg',
                        'results/final_benchmark_analysis.json',
                        'results/mixed_policy.json', '.github/workflows/cpu-checks.yml']
            excluded = ['results/raw/requests.jsonl', 'results/run1/result.json',
                        'results/live_gateway_smoke.json', 'AGENTS.md', '.env',
                        'work/id_ed25519', 'extensions/__pycache__/x.pyc']
            for name in included + excluded:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}', encoding='utf-8')
            names = {p.relative_to(root).as_posix() for p in public_files(root)}
            self.assertEqual(names, set(included))

    def test_sensitive_markers_report_categories_not_values(self):
        data = b'-----BEGIN ' + b'OPENSSH PRIVATE KEY-----'
        self.assertEqual(content_issues(Path('example.txt'), data), ['private-key'])
        host = b'connect.' + b'example.seetacloud.com'
        self.assertEqual(content_issues(Path('example.txt'), host), ['cloud-login-host'])


if __name__ == '__main__':
    unittest.main()
