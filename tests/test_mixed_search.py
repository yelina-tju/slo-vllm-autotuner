from pathlib import Path
import unittest

from slo_autotuner.mixed import RequestClass
from slo_autotuner.mixed_search import (
    MixedCandidateSpec,
    MixedRun,
    aggregate_mixed_runs,
    evaluate_mixed_candidate,
    select_mixed_candidate,
)


SHORT = RequestClass("short", 0.8, 256, 64, 100, 400)
LONG = RequestClass("long", 0.2, 2048, 64, 295, 500)


def run(
    rate: float,
    seed: int,
    passes: bool,
    short_e2e: float,
    long_e2e: float,
) -> MixedRun:
    return MixedRun(
        source=Path(f"rps{rate}_seed{seed}.json"),
        offered_rps=rate,
        seed=seed,
        duration_s=10,
        request_throughput=rate,
        request_goodput=rate if passes else rate * 0.9,
        all_classes_meet_slo=passes,
        classes={
            "short": {"p99_ttft_ms": 60, "p99_e2el_ms": short_e2e},
            "long": {"p99_ttft_ms": 100, "p99_e2el_ms": long_e2e},
        },
    )


class MixedSearchTest(unittest.TestCase):
    def test_three_passes_are_required_for_robust_capacity(self) -> None:
        candidate = MixedCandidateSpec("candidate", 1024, "fcfs", ())
        evaluation = evaluate_mixed_candidate(
            candidate,
            [
                run(3, 1, True, 380, 450),
                run(3, 2, True, 385, 455),
                run(3, 3, True, 390, 460),
                run(4, 1, False, 410, 470),
                run(4, 2, True, 395, 465),
                run(4, 3, False, 420, 475),
            ],
            (SHORT, LONG),
            min_repetitions=3,
            required_pass_rate=1.0,
        )

        self.assertEqual(evaluation.robust_capacity_rps, 3)
        self.assertEqual(evaluation.aggregate_at(4).feasible_trials, 1)

    def test_tie_break_prefers_more_tail_headroom(self) -> None:
        low_tail = evaluate_mixed_candidate(
            MixedCandidateSpec("low_tail", 1024, "fcfs", ()),
            [run(3, seed, True, 380, 450) for seed in (1, 2, 3)],
            (SHORT, LONG),
            3,
            1.0,
        )
        high_tail = evaluate_mixed_candidate(
            MixedCandidateSpec("high_tail", 2048, "fcfs", ()),
            [run(3, seed, True, 390, 450) for seed in (1, 2, 3)],
            (SHORT, LONG),
            3,
            1.0,
        )

        selected = select_mixed_candidate((high_tail, low_tail), (SHORT, LONG))

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.candidate.name, "low_tail")

    def test_duplicate_seed_at_one_rate_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            aggregate_mixed_runs(
                [run(3, 1, True, 380, 450), run(3, 1, True, 381, 451)],
                ("short", "long"),
            )


if __name__ == "__main__":
    unittest.main()
