from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "summarize_asymmetric_recovery.py"
SPEC = importlib.util.spec_from_file_location("summarize_asymmetric_recovery", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AsymmetricRecoverySummaryTest(unittest.TestCase):
    def test_first_transition_delay_ignores_pre_boundary_targets(self) -> None:
        result = {
            "executions": [
                {"target_policy": "balanced:old", "started_offset_s": 100},
                {"target_policy": "mixed_80_20:selected", "started_offset_s": 140},
                {"target_policy": "balanced:new", "started_offset_s": 225},
            ]
        }
        self.assertEqual(
            MODULE.first_transition_delay(result, "balanced:", 210), 15
        )

    def test_summarize_values_uses_seed_level_sample_dispersion(self) -> None:
        summary = MODULE.summarize_values([1.0, 2.0, 3.0])
        self.assertEqual(
            summary,
            {"mean": 2.0, "sample_stdev": 1.0, "min": 1.0, "max": 3.0},
        )


if __name__ == "__main__":
    unittest.main()
