from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_experiment017_capacity.py"
SPEC = importlib.util.spec_from_file_location(SCRIPT.stem, SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Experiment017CapacityAuditTest(unittest.TestCase):
    def test_complete_triplets_stop_at_first_failure(self) -> None:
        observations = {
            1.0: {1: True, 2: True, 3: True},
            2.0: {1: True, 2: False, 3: True},
        }
        rows, errors = MODULE.audit_stage(observations, [1, 2, 4], [1, 2, 3])
        self.assertEqual(errors, [])
        self.assertTrue(rows[0]["robust"])
        self.assertFalse(rows[1]["robust"])

    def test_higher_rate_after_failure_is_rejected(self) -> None:
        observations = {
            1.0: {1: True, 2: False, 3: True},
            2.0: {1: True, 2: True, 3: True},
        }
        _, errors = MODULE.audit_stage(observations, [1, 2], [1, 2, 3])
        self.assertIn("rate 2 was run after the first non-robust rate", errors)

    def test_incomplete_seed_triplet_is_rejected(self) -> None:
        _, errors = MODULE.audit_stage(
            {1.0: {1: True, 2: True}}, [1], [1, 2, 3]
        )
        self.assertRegex(errors[0], "expected")


if __name__ == "__main__":
    unittest.main()
