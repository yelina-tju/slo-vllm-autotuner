from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "prepare_experiment017_capacity_extension.py"
)
SPEC = importlib.util.spec_from_file_location(SCRIPT.stem, SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Experiment017CapacityExtensionTest(unittest.TestCase):
    def test_only_right_censored_candidates_are_triggered(self) -> None:
        policy = {
            "candidate_capacity_bound_status": {
                "mbt1024_fcfs": "right_censored_lower_bound",
                "mbt2048_fcfs": "bounded_by_observed_failure",
            }
        }
        self.assertEqual(
            MODULE.right_censored_candidates(policy), ["mbt1024_fcfs"]
        )

    def test_missing_bound_status_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "lacks"):
            MODULE.right_censored_candidates({})

    def test_extension_uses_new_disjoint_seeds_and_fixed_grid(self) -> None:
        base = {
            "description": "base",
            "seeds": [111, 112, 113],
            "planned_rates_rps": [1, 2, 4, 6, 8, 10, 12],
            "candidates": [],
        }
        manifest = MODULE.build_extension_manifest(
            base, "balanced", ["mbt1024_fcfs"]
        )
        self.assertTrue(set(base["seeds"]).isdisjoint(MODULE.EXTENSION_SEEDS))
        self.assertEqual(manifest["extension_seeds"], [114, 115, 116])
        self.assertEqual(manifest["extension_planned_rates_rps"], [14, 16, 18, 20, 24])
        self.assertEqual(manifest["planned_rates_rps"][-1], 24.0)


if __name__ == "__main__":
    unittest.main()
