from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PREPARE = load_script("prepare_experiment017_capacity.py")
CHECK = load_script("check_capacity_result.py")


class Experiment017CapacityTest(unittest.TestCase):
    def test_rate_grids_are_ascending_and_seeds_are_disjoint(self) -> None:
        self.assertEqual(PREPARE.SEEDS, [111, 112, 113])
        self.assertTrue(all(
            rates == sorted(set(rates)) for rates in PREPARE.RATE_GRIDS.values()
        ))
        self.assertTrue({101, 102, 103}.isdisjoint(PREPARE.SEEDS))

    def test_result_validator_checks_frozen_metadata(self) -> None:
        args = argparse.Namespace(
            model="qwen2.5-7b", seed=111, rate=2.0, mbt=1024, num_prompts=160,
            path=Path("unused"),
        )
        payload = {
            "model": "qwen2.5-7b", "seed": 111, "request_rate": 2,
            "attempted": 160, "completed": 160, "failed": 0,
            "all_classes_meet_slo": True,
            "server": {
                "max_num_batched_tokens": "1024", "max_num_seqs": "256",
                "scheduling_policy": "fcfs", "prefix_caching": "false",
            },
        }
        original = CHECK.json.loads
        CHECK.json.loads = lambda _: payload
        args.path = type("P", (), {"read_text": lambda self, **kwargs: "{}"})()
        try:
            self.assertTrue(CHECK.validate(args))
            payload["server"]["prefix_caching"] = "true"
            with self.assertRaisesRegex(ValueError, "metadata"):
                CHECK.validate(args)
        finally:
            CHECK.json.loads = original


if __name__ == "__main__":
    unittest.main()
