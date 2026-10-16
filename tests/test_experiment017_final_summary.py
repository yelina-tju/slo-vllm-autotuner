from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "summarize_experiment017_final.py"
SPEC = importlib.util.spec_from_file_location("summarize_experiment017_final", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Experiment017FinalSummaryTest(unittest.TestCase):
    def test_four_seed_interval_uses_df3_student_t(self) -> None:
        summary = MODULE.summarize([-1, -2, -3, -4], paired=True)
        self.assertEqual(summary["n"], 4)
        self.assertEqual(summary["mean"], -2.5)
        self.assertLess(summary["ci95_low"], -4.5)
        self.assertGreater(summary["ci95_high"], -0.5)

    def test_cyclic_order_balances_every_position(self) -> None:
        modes = list(MODULE.MODES)
        orders = [modes[offset:] + modes[:offset] for offset in range(4)]
        MODULE.validate_order(orders)

    def test_full_recovery_ignores_canary_stages(self) -> None:
        result = {"executions": [
            {"status": "applied", "started_offset_s": 220,
             "completed_offset_s": 221, "target_policy": "balanced:x:canary-4.5rps"},
            {"status": "applied", "started_offset_s": 250,
             "completed_offset_s": 251, "target_policy": "balanced:x"},
        ]}
        self.assertEqual(MODULE.transition_delay(result, 210, "balanced:", True), 41)

    def test_missing_transition_is_reported_instead_of_crashing(self) -> None:
        rows = []
        for seed in MODULE.SEEDS:
            for mode in ("canary_recovery", "binary_recovery"):
                item = {"seed": seed, "mode": mode}
                for metric in MODULE.NUMERIC_METRICS:
                    item[metric] = 1.0
                for metric in MODULE.TRANSITION_METRICS:
                    item[metric] = 10.0
                rows.append(item)
        next(
            item for item in rows
            if item["seed"] == 124 and item["mode"] == "canary_recovery"
        )["full_capacity_recovery_delay_s"] = None

        summary = MODULE.paired(rows, "canary_recovery", "binary_recovery")

        endpoint = summary["full_capacity_recovery_delay_s"]
        self.assertEqual(endpoint["n"], 3)
        self.assertEqual(endpoint["missing_seeds"], [124])
        self.assertIsNone(endpoint["ci95_low"])
        self.assertEqual(
            endpoint["inference_status"],
            "incomplete_endpoint_no_preregistered_ci",
        )


if __name__ == "__main__":
    unittest.main()
