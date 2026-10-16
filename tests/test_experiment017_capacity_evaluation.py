from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_mixed_search.py"
SPEC = importlib.util.spec_from_file_location("evaluate_mixed_search", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Evaluation:
    def __init__(self, capacity, observed_rates):
        self.robust_capacity_rps = capacity
        self.rates = [type("Rate", (), {"offered_rps": rate})() for rate in observed_rates]


class Experiment017CapacityEvaluationTest(unittest.TestCase):
    def test_passed_grid_ceiling_is_a_lower_bound(self) -> None:
        self.assertEqual(
            MODULE.capacity_bound_status(
                Evaluation(12, [1, 2, 4, 6, 8, 10, 12]),
                [1, 2, 4, 6, 8, 10, 12],
            ),
            "right_censored_lower_bound",
        )

    def test_failure_above_capacity_bounds_search(self) -> None:
        self.assertEqual(
            MODULE.capacity_bound_status(
                Evaluation(10, [1, 2, 4, 6, 8, 10, 12]),
                [1, 2, 4, 6, 8, 10, 12],
            ),
            "bounded_by_observed_failure",
        )

    def test_unobserved_planned_rates_do_not_create_a_false_boundary(self) -> None:
        self.assertEqual(
            MODULE.capacity_bound_status(
                Evaluation(10, [1, 2, 4, 6, 8, 10]),
                [1, 2, 4, 6, 8, 10, 12],
            ),
            "right_censored_lower_bound",
        )


if __name__ == "__main__":
    unittest.main()
