from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "summarize_final_benchmark.py"
SPEC = importlib.util.spec_from_file_location("summarize_final_benchmark", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FinalBenchmarkSummaryTest(unittest.TestCase):
    def test_sample_summary_uses_seed_level_dispersion(self) -> None:
        self.assertEqual(
            MODULE.summarize_values([1.0, 2.0, 3.0]),
            {
                "mean": 2.0,
                "sample_stdev": 1.0,
                "min": 1.0,
                "max": 3.0,
            },
        )

    def test_cyclic_orders_balance_every_execution_position(self) -> None:
        modes = list(MODULE.MODES)
        orders = [modes[offset:] + modes[:offset] for offset in range(len(modes))]
        MODULE.validate_cyclic_orders(orders)

    def test_nonbalanced_order_is_rejected(self) -> None:
        modes = list(MODULE.MODES)
        with self.assertRaises(ValueError):
            MODULE.validate_cyclic_orders([modes] * len(modes))

    def test_paired_summary_uses_small_sample_t_interval(self) -> None:
        summary = MODULE.summarize_paired_values([-1, -2, -3, -4, -5])
        self.assertEqual(summary["n"], 5)
        self.assertEqual(summary["mean"], -3)
        self.assertLess(summary["ci95_low"], -4.9)
        self.assertGreater(summary["ci95_high"], -1.1)
        self.assertLess(summary["ci95_high"], 0)

    def test_paired_summary_rejects_unregistered_seed_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires 5"):
            MODULE.summarize_paired_values([1, 2, 3, 4])

    def test_full_capacity_delay_ignores_canary_stages(self) -> None:
        result = {
            "executions": [
                {
                    "status": "applied",
                    "started_offset_s": 220,
                    "completed_offset_s": 221,
                    "target_policy": "balanced:x:canary-8rps",
                },
                {
                    "status": "applied",
                    "started_offset_s": 250,
                    "completed_offset_s": 251,
                    "target_policy": "balanced:x",
                },
            ]
        }
        self.assertEqual(
            MODULE.transition_delay(
                result, 210, "balanced:", require_full_capacity=True
            ),
            41,
        )


if __name__ == "__main__":
    unittest.main()
