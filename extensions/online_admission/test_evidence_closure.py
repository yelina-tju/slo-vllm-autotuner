import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from recheck_guarded_evidence import check_files
from guarded_diagnostics import diagnostic


class ClosureTest(unittest.TestCase):
    def test_archive_hash_and_tampering(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root/'evidence').write_bytes(b'fixture')
            expected = {'evidence': hashlib.sha256(b'fixture').hexdigest()}
            with patch('recheck_guarded_evidence.ARCHIVES', expected):
                self.assertEqual(check_files(root), expected)
                (root/'evidence').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'hash mismatch'): check_files(root)

    def test_missing_archive_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as name:
            with patch('recheck_guarded_evidence.ARCHIVES', {'missing': 'hash'}):
                with self.assertRaises(FileNotFoundError): check_files(Path(name))

    def test_old_duration_not_relabelled_by_diagnostic(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            case = root/'seed401-low'
            (case/'fixed').mkdir(parents=True)
            (case/'analysis.json').write_text(json.dumps(dict(arm='low')))
            (case/'fixed/run_metadata.json').write_text(json.dumps(dict(duration=240)))
            with self.assertRaisesRegex(ValueError, 'require260s'): diagnostic(root)


if __name__ == '__main__': unittest.main()
