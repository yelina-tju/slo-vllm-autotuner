import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from runtime_paths import gpu_paths


class RuntimePathsTest(unittest.TestCase):
    def test_missing_model_fails_before_launch(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'MODEL_PATH'):
                gpu_paths()

    def test_space_in_model_path_and_explicit_executable(self):
        with tempfile.TemporaryDirectory(prefix='model path ') as directory:
            with patch.dict(os.environ, {'MODEL_PATH': directory, 'VLLM_BIN': sys.executable}):
                self.assertEqual(gpu_paths(), (Path(directory).resolve(), Path(sys.executable).resolve()))

    def test_missing_executable_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'MODEL_PATH': directory, 'VLLM_BIN': str(Path(directory) / 'missing')}):
                with self.assertRaisesRegex(ValueError, 'VLLM_BIN'):
                    gpu_paths()
