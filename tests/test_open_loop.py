from pathlib import Path
import json
import tempfile
import unittest

from slo_autotuner.open_loop import (
    OpenLoopRun,
    aggregate_by_rate,
    select_best_open_loop_run,
    select_empirically_safe_rate,
    wilson_interval,
)
from slo_autotuner.search import (
    CandidateSpec,
    classify_rate,
    evaluate_candidate_runs,
    select_candidate,
)


def run(
    offered_rps: float,
    goodput: float,
    ttft: float,
    e2e: float,
    violations: int = 0,
) -> OpenLoopRun:
    return OpenLoopRun(
        source=Path(f"rps{offered_rps}.json"),
        offered_rps=offered_rps,
        completed=100,
        failed=0,
        achieved_rps=offered_rps * 0.9,
        request_goodput_rps=goodput,
        p99_ttft_ms=ttft,
        p99_e2el_ms=e2e,
        ttft_violations=0,
        e2el_violations=0,
        any_slo_violations=violations,
    )


class OpenLoopSelectorTest(unittest.TestCase):
    def test_loads_workload_and_scheduler_metadata(self) -> None:
        payload = {
            "request_rate": 9,
            "completed": 2,
            "failed": 0,
            "request_throughput": 8.9,
            "request_goodput": 8.8,
            "duration": 2 / 8.9,
            "p99_ttft_ms": 80,
            "p99_e2el_ms": 1200,
            "ttfts": [0.05, 0.06],
            "itls": [[0.004], [0.005]],
            "seed": "31",
            "server_prefix_caching": "false",
            "server_max_num_batched_tokens": "2048",
            "server_max_num_seqs": "256",
            "workload_name": "decode_heavy_4x",
            "input_tokens": "256",
            "output_tokens": "256",
            "ttft_slo_ms": "100",
            "e2el_slo_ms": "1300",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = OpenLoopRun.from_json(path, 100, 1300)

        self.assertEqual(loaded.workload_name, "decode_heavy_4x")
        self.assertEqual(loaded.input_tokens, 256)
        self.assertEqual(loaded.output_tokens, 256)
        self.assertEqual(loaded.configured_ttft_slo_ms, 100)
        self.assertEqual(loaded.configured_e2el_slo_ms, 1300)
        self.assertEqual(loaded.server_max_num_batched_tokens, 2048)
        self.assertEqual(loaded.server_max_num_seqs, 256)
        self.assertAlmostEqual(loaded.request_goodput_rps, 8.9)

    def test_recomputes_goodput_for_new_slo_thresholds(self) -> None:
        payload = {
            "request_rate": 5,
            "completed": 2,
            "failed": 0,
            "duration": 1,
            "request_throughput": 2,
            "request_goodput": 2,
            "p99_ttft_ms": 100,
            "p99_e2el_ms": 500,
            "ttfts": [0.05, 0.05],
            "itls": [[0.3], [0.5]],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = OpenLoopRun.from_json(path, 180, 440)

        self.assertEqual(loaded.any_slo_violations, 1)
        self.assertEqual(loaded.request_goodput_rps, 1)

    def test_selects_highest_goodput_feasible_window(self) -> None:
        selected = select_best_open_loop_run(
            [
                run(20, 18.8, 47.5, 350.0),
                run(45, 39.2, 66.3, 387.3),
                run(50, 37.0, 162.0, 477.1),
            ],
            max_p99_ttft_ms=100,
            max_p99_e2el_ms=400,
        )

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.offered_rps, 45)

    def test_request_compliance_is_separate_from_window_slo(self) -> None:
        candidate = run(50, 37.0, 162.0, 477.1, violations=14)

        self.assertAlmostEqual(candidate.request_compliance_rate, 0.86)
        self.assertFalse(candidate.window_meets_slo(100, 400))

    def test_repeated_policy_rejects_a_rate_that_only_sometimes_passes(self) -> None:
        runs = [
            run(22, 21.7, 75.6, 395.8),
            run(22, 21.8, 72.6, 387.8),
            run(22, 21.7, 64.8, 393.9),
            run(25, 24.3, 66.5, 415.2),
            run(25, 24.8, 67.9, 388.4),
            run(25, 24.1, 80.2, 409.8),
        ]
        aggregates = aggregate_by_rate(runs, 100, 400)

        selected = select_empirically_safe_rate(
            aggregates,
            min_repetitions=3,
            required_pass_rate=1.0,
            max_p99_ttft_ms=100,
            max_p99_e2el_ms=400,
        )

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.offered_rps, 22)

    def test_safety_margin_can_reject_a_near_boundary_rate(self) -> None:
        aggregates = aggregate_by_rate(
            [
                run(22, 21.7, 75.6, 395.8),
                run(22, 21.8, 72.6, 387.8),
                run(22, 21.7, 64.8, 393.9),
            ],
            100,
            400,
        )

        selected = select_empirically_safe_rate(
            aggregates,
            min_repetitions=3,
            required_pass_rate=1.0,
            max_p99_ttft_ms=100,
            max_p99_e2el_ms=400,
            e2el_safety_margin_ms=5,
        )

        self.assertIsNone(selected)

    def test_wilson_interval_does_not_treat_three_passes_as_certainty(self) -> None:
        low, high = wilson_interval(3, 3)

        self.assertAlmostEqual(low, 0.4385, places=4)
        self.assertEqual(high, 1.0)

    def test_sparse_scheduler_evidence_is_only_provisional(self) -> None:
        candidate = CandidateSpec("mbt2048", 2048, 256, ())
        evaluation = evaluate_candidate_runs(
            candidate,
            [
                run(23, 22.8, 67.0, 389.3),
                run(24, 23.7, 67.7, 388.9),
                run(25, 24.3, 66.5, 415.2),
            ],
            min_repetitions=3,
            required_pass_rate=1.0,
            max_p99_ttft_ms=100,
            max_p99_e2el_ms=400,
        )

        self.assertIsNone(evaluation.robust_capacity_rps)
        self.assertEqual(evaluation.observed_capacity_rps, 24)
        self.assertEqual(
            classify_rate(
                evaluation.aggregate_at(24),
                min_repetitions=3,
                required_pass_rate=1.0,
                max_p99_ttft_ms=100,
                max_p99_e2el_ms=400,
            ),
            "observed_feasible_needs_repetition",
        )

    def test_provisional_selector_prefers_capacity_then_tail_headroom(self) -> None:
        policy = {
            "min_repetitions": 3,
            "required_pass_rate": 1.0,
            "max_p99_ttft_ms": 100,
            "max_p99_e2el_ms": 400,
        }
        candidate_1024 = evaluate_candidate_runs(
            CandidateSpec("mbt1024", 1024, 256, ()),
            [run(24, 23.8, 67.0, 391.4)],
            **policy,
        )
        candidate_2048 = evaluate_candidate_runs(
            CandidateSpec("mbt2048", 2048, 256, ()),
            [run(24, 23.7, 67.7, 388.9)],
            **policy,
        )

        selected, is_robust = select_candidate(
            [candidate_1024, candidate_2048]
        )

        self.assertFalse(is_robust)
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.candidate.name, "mbt2048")


if __name__ == "__main__":
    unittest.main()
