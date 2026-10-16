from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from slo_autotuner.comparison import (
    build_trace,
    describe_model,
    fingerprint,
    score_records,
    score_windows,
)
from slo_autotuner.mixed import RequestClass


class ComparisonTest(unittest.TestCase):
    def test_model_provenance_separates_alias_config_and_weight_size(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").write_text('{"model_type":"qwen2"}')
            (root / "tokenizer_config.json").write_text('{"vocab":1}')
            (root / "model-00001-of-00001.safetensors").write_bytes(b"weights")

            first = describe_model(root, "model-a")
            second = describe_model(root, "model-b")

        self.assertEqual(first["weight_bytes"], 7)
        self.assertEqual(first["weight_files"][0]["size_bytes"], 7)
        self.assertNotEqual(first["served_model_name"], second["served_model_name"])
        self.assertEqual(
            first["identity_file_sha256"], second["identity_file_sha256"]
        )

    def test_incomplete_model_directory_is_rejected(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                describe_model(Path(directory), "missing")

    def test_reproducible_open_loop_trace_with_fixed_phase_boundaries(self):
        config = {"seed": 81, "phases": [
            {"name": "a", "duration_s": 10, "request_rate": 10, "long_fraction": 0},
            {"name": "b", "duration_s": 10, "request_rate": 10, "long_fraction": 0.2},
        ]}
        first, phases = build_trace(config)
        second, _ = build_trace(config)
        self.assertEqual(fingerprint(first), fingerprint(second))
        self.assertEqual(phases[-1]["end_s"], 20)
        self.assertTrue(all(0 <= r["scheduled_offset_s"] < 10 for r in first if r["phase"] == "a"))
        self.assertTrue(all(10 <= r["scheduled_offset_s"] < 20 for r in first if r["phase"] == "b"))
        self.assertTrue(any(r["class_name"] == "document_long" for r in first))
        self.assertNotEqual(fingerprint(first), fingerprint(build_trace({**config, "seed": 82})[0]))

    def test_rejections_and_tail_failures_both_reduce_goodput(self):
        spec = RequestClass("short", 1, 256, 64, 100, 400)
        base = {"class_name": "short", "client_launch_delay_ms": 0,
                "scheduled_offset_s": 1, "ttft_ms": 50, "e2el_ms": 300,
                "status_code": 200, "error": None}
        records = [base, {**base, "ttft_ms": 150},
                   {**base, "status_code": 429, "ttft_ms": None, "error": "rate"},
                   {**base, "status_code": 503, "ttft_ms": None, "error": "pause"}]
        summary = score_records(records, [spec], 10)
        self.assertEqual(summary["slo_compliant"], 1)
        self.assertEqual(summary["request_goodput"], 0.1)
        self.assertEqual(summary["request_compliance_rate"], 0.25)
        self.assertEqual(summary["backend_or_transport_errors"], 0)
        self.assertEqual(summary["classes"]["short"]["slo_violations"], 3)

    def test_reject_everything_does_not_look_like_a_passed_slo_window(self):
        spec = RequestClass("short", 1, 256, 64, 100, 400)
        record = {"class_name": "short", "client_launch_delay_ms": 0,
                  "scheduled_offset_s": 1, "ttft_ms": None, "e2el_ms": 1,
                  "status_code": 503, "error": "paused"}
        result = score_windows([record], [spec], 30, 30)
        self.assertEqual(result["class_windows_without_success"], 1)
        self.assertEqual(result["windows"][0]["request_goodput"], 0)
        self.assertFalse(result["windows"][0]["all_classes_meet_slo"])

    def test_tail_area_uses_fixed_nonoverlapping_windows(self):
        spec = RequestClass("short", 1, 256, 64, 100, 400)
        records = [{"class_name": "short", "client_launch_delay_ms": 0,
                    "scheduled_offset_s": offset, "ttft_ms": ttft, "e2el_ms": 300,
                    "status_code": 200, "error": None}
                   for offset, ttft in [(1, 200), (31, 50)]]
        result = score_windows(records, [spec], 60, 30)
        self.assertEqual(result["tail_violation_area_s"], 30)
        self.assertEqual(len(result["windows"]), 2)


if __name__ == "__main__":
    unittest.main()
