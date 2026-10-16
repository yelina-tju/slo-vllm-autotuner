from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "derive_generalization_slos.py"
SPEC = importlib.util.spec_from_file_location("derive_generalization_slos", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def payload(seed: int, short: tuple[float, float], long: tuple[float, float]) -> dict:
    specs = [
        {"name": "interactive_short", "weight": 0.8, "input_tokens": 256,
         "output_tokens": 64, "priority": 0},
        {"name": "document_long", "weight": 0.2, "input_tokens": 2048,
         "output_tokens": 64, "priority": 1},
    ]
    return {
        "model": "qwen2.5-7b",
        "seed": seed,
        "request_rate": 1.0,
        "failed": 0,
        "class_specs": specs,
        "classes": {
            "interactive_short": {"p99_ttft_ms": short[0], "p99_e2el_ms": short[1]},
            "document_long": {"p99_ttft_ms": long[0], "p99_e2el_ms": long[1]},
        },
    }


class GeneralizationSloDerivationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.paths = []
        values = [
            payload(101, (20, 300), (70, 360)),
            payload(102, (25, 290), (65, 400)),
            payload(103, (22, 310), (80, 380)),
        ]
        for item in values:
            path = Path(self.temp.name) / f"seed{item['seed']}.json"
            path.write_text(json.dumps(item), encoding="utf-8")
            self.paths.append(path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_uses_worst_seed_before_applying_factors(self) -> None:
        runs = MODULE.load_runs(self.paths, {101, 102, 103})
        config, evidence = MODULE.derive(runs)
        classes = {item["name"]: item for item in config["classes"]}
        self.assertEqual(classes["interactive_short"]["ttft_slo_ms"], 75)
        self.assertEqual(classes["interactive_short"]["e2el_slo_ms"], 434)
        self.assertEqual(classes["document_long"]["ttft_slo_ms"], 240)
        self.assertEqual(classes["document_long"]["e2el_slo_ms"], 560)
        self.assertEqual(evidence["seeds"], [101, 102, 103])

    def test_rejects_seed_leakage_or_missing_seed(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected calibration seeds"):
            MODULE.load_runs(self.paths[:2], {101, 102, 103})

    def test_rejects_non_low_load_input(self) -> None:
        changed = json.loads(self.paths[0].read_text(encoding="utf-8"))
        changed["request_rate"] = 2.0
        self.paths[0].write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "1 req/s"):
            MODULE.load_runs(self.paths, {101, 102, 103})


if __name__ == "__main__":
    unittest.main()
