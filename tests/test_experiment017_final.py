from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_experiment017_final.py"
SPEC = importlib.util.spec_from_file_location("prepare_experiment017_final", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def fixture(candidate: str = "mbt1024_fcfs"):
    balanced = {
        "status": "ready",
        "selected": {"candidate": "mbt2048_fcfs", "admission_limit_rps": 12},
        "candidate_capacities": {"mbt1024_fcfs": 10, "mbt2048_fcfs": 12},
    }
    mixed = {
        "status": "ready",
        "selected": {
            "candidate": candidate,
            "admission_limit_rps": 2,
            "max_num_batched_tokens": int(candidate[3:7]),
            "scheduling_policy": "fcfs",
        },
    }
    workload = {
        "classes": [
            {"name": "interactive_short", "weight": 0.8, "input_tokens": 256,
             "output_tokens": 64, "ttft_slo_ms": 700, "e2el_slo_ms": 2400,
             "priority": 0},
            {"name": "document_long", "weight": 0.2, "input_tokens": 2048,
             "output_tokens": 64, "ttft_slo_ms": 1600, "e2el_slo_ms": 2700,
             "priority": 1},
        ]
    }
    controller = {"compatible_recovery_canary_admission_limits_rps": [8, 16]}
    return balanced, mixed, workload, controller


class Experiment017FinalTest(unittest.TestCase):
    def test_canary_stages_are_derived_from_compatible_capacity(self) -> None:
        artifacts = MODULE.build_artifacts(*fixture())
        self.assertEqual(artifacts["low_capacity_rps"], 2)
        self.assertEqual(artifacts["high_compatible_capacity_rps"], 10)
        self.assertEqual(artifacts["canary_limits_rps"], [4.5, 7.0])
        self.assertEqual(artifacts["balanced_offered_rps"], 6.5)
        self.assertEqual(artifacts["mixed_offered_rps"], 4)

    def test_final_seeds_are_cyclic_and_disjoint_from_calibration(self) -> None:
        artifacts = MODULE.build_artifacts(*fixture())
        orders = [
            [mode["name"] for mode in item["payload"]["modes"]]
            for item in artifacts["configs"]
        ]
        for position in range(4):
            self.assertEqual(
                {order[position] for order in orders}, set(MODULE.MODE_ORDER)
            )
        self.assertTrue(
            set(MODULE.FINAL_SEEDS).isdisjoint(
                {101, 102, 103, 111, 112, 113, 114, 115, 116}
            )
        )

    def test_stops_when_two_distinct_canary_stages_do_not_fit(self) -> None:
        with self.assertRaisesRegex(ValueError, "two distinct"):
            MODULE.derive_canary_limits(2, 3)

    def test_stops_without_compatible_balanced_evidence(self) -> None:
        balanced, mixed, workload, controller = fixture("mbt4096_fcfs")
        with self.assertRaisesRegex(ValueError, "no evidence-backed"):
            MODULE.build_artifacts(balanced, mixed, workload, controller)

    def test_stops_when_capacity_grid_ceiling_passed(self) -> None:
        balanced, mixed, workload, controller = fixture()
        balanced["candidate_capacity_bound_status"] = {
            "mbt1024_fcfs": "right_censored_lower_bound"
        }
        with self.assertRaisesRegex(ValueError, "right-censored"):
            MODULE.build_artifacts(balanced, mixed, workload, controller)


if __name__ == "__main__":
    unittest.main()
