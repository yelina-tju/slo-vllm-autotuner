from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from run_controller_safety_scenarios import run_scenarios  # noqa: E402
from slo_autotuner.controller import ControllerConfig  # noqa: E402


class ControllerSafetyScenariosTest(unittest.TestCase):
    def test_each_targeted_scenario_separates_the_component(self) -> None:
        config = ControllerConfig.from_json(PROJECT_ROOT / "configs" / "controller.json")

        result = run_scenarios(config, restart_cost_s=45.0)

        self.assertEqual(
            result["expected_restart_pairs"],
            {
                "transient_false_positive": (0, 1),
                "weak_distance_advantage": (0, 1),
                "rapid_incompatible_reversal": (1, 3),
                "persistent_fresh_slo_violations": (1, 0),
                "compatible_high_capacity_recovery": (0, 0),
            },
        )
        recovery = result["scenarios"]["compatible_high_capacity_recovery"]
        self.assertEqual(recovery["asymmetric"]["actions"], ["switch"])
        self.assertEqual(recovery["legacy_symmetric"]["actions"], ["hold"])


if __name__ == "__main__":
    unittest.main()
