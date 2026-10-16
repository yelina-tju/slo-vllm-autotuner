import unittest

from slo_autotuner.mixed import (
    RequestClass,
    allocate_request_classes,
    completion_event_has_token,
    percentile,
    poisson_arrival_offsets,
    summarize_records,
)


SHORT = RequestClass("short", 0.8, 256, 64, 100, 400)
LONG = RequestClass("long", 0.2, 2048, 64, 295, 500)


class MixedWorkloadTest(unittest.TestCase):
    def test_exact_class_counts_are_stable_for_paired_trials(self) -> None:
        first = allocate_request_classes((SHORT, LONG), 101, seed=41)
        second = allocate_request_classes((SHORT, LONG), 101, seed=41)

        self.assertEqual([item.name for item in first], [item.name for item in second])
        self.assertEqual(sum(item.name == "short" for item in first), 81)
        self.assertEqual(sum(item.name == "long" for item in first), 20)

    def test_lower_priority_number_is_preserved_from_manifest_shape(self) -> None:
        long_with_priority = RequestClass("long", 0.2, 2048, 64, 295, 500, 1)

        self.assertLess(SHORT.priority, long_with_priority.priority)

    def test_poisson_schedule_is_deterministic_and_monotonic(self) -> None:
        first = poisson_arrival_offsets(10, request_rate=5, seed=42)
        second = poisson_arrival_offsets(10, request_rate=5, seed=42)

        self.assertEqual(first, second)
        self.assertEqual(first[0], 0)
        self.assertTrue(all(left < right for left, right in zip(first, first[1:])))

    def test_percentile_uses_linear_interpolation(self) -> None:
        self.assertEqual(percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertAlmostEqual(percentile([1, 2, 3, 4], 0.99), 3.97)
        self.assertIsNone(percentile([], 0.99))

    def test_token_ids_detect_a_generated_special_token_with_empty_text(self) -> None:
        event = {"choices": [{"text": "", "token_ids": [151643]}]}

        self.assertTrue(completion_event_has_token(event))

    def test_class_slos_are_evaluated_independently(self) -> None:
        records = [
            {"class_name": "short", "ttft_ms": 80, "e2el_ms": 350, "error": None},
            {"class_name": "short", "ttft_ms": 120, "e2el_ms": 390, "error": None},
            {"class_name": "long", "ttft_ms": 250, "e2el_ms": 500, "error": None},
        ]

        summary = summarize_records(records, (SHORT, LONG), duration_s=1)

        self.assertFalse(summary["all_classes_meet_slo"])
        self.assertEqual(summary["request_goodput"], 2)
        self.assertEqual(summary["classes"]["short"]["slo_violations"], 1)
        self.assertFalse(summary["classes"]["short"]["window_meets_slo"])
        self.assertTrue(summary["classes"]["long"]["window_meets_slo"])

    def test_transport_failure_counts_as_slo_violation(self) -> None:
        records = [
            {"class_name": "short", "ttft_ms": None, "e2el_ms": 10, "error": "boom"},
            {"class_name": "long", "ttft_ms": 250, "e2el_ms": 500, "error": None},
        ]

        summary = summarize_records(records, (SHORT, LONG), duration_s=2)

        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["classes"]["short"]["slo_violations"], 1)
        self.assertFalse(summary["classes"]["short"]["window_meets_slo"])


if __name__ == "__main__":
    unittest.main()
