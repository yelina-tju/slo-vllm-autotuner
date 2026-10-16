from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_experiment017_model.py"
SPEC = importlib.util.spec_from_file_location("download_experiment017_model", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Experiment017ModelDownloadTest(unittest.TestCase):
    def test_validates_sharded_model_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").write_text(
                json.dumps({"model_type": "qwen2", "num_hidden_layers": 28}),
                encoding="utf-8",
            )
            (root / "model-00001-of-00002.safetensors").write_bytes(b"one")
            (root / "model-00002-of-00002.safetensors").write_bytes(b"two")
            (root / "model.safetensors.index.json").write_text("{}", encoding="utf-8")
            result = MODULE.validate_model(root)
            self.assertEqual(result["model_type"], "qwen2")
            self.assertEqual(result["num_hidden_layers"], 28)
            self.assertEqual(result["weight_bytes"], 6)

    def test_rejects_incomplete_sharded_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").write_text("{}", encoding="utf-8")
            (root / "one.safetensors").write_bytes(b"one")
            (root / "two.safetensors").write_bytes(b"two")
            with self.assertRaisesRegex(ValueError, "index"):
                MODULE.validate_model(root)


if __name__ == "__main__":
    unittest.main()
