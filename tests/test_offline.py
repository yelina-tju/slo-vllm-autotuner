from pathlib import Path
import unittest

from slo_autotuner.offline import BenchmarkRun, select_best_run


def run(concurrency: int, throughput: float, ttft: float, e2e: float) -> BenchmarkRun:
    return BenchmarkRun(
        source=Path(f"c{concurrency}.json"),
        concurrency=concurrency,
        completed=64,
        failed=0,
        request_throughput=1.0,
        output_throughput=throughput,
        p99_ttft_ms=ttft,
        p99_tpot_ms=5.0,
        p99_e2el_ms=e2e,
    )


class OfflineSelectorTest(unittest.TestCase):
    def test_selects_fastest_feasible_configuration(self) -> None:
        runs = [
            run(8, 1451.87, 81.09, 364.31),
            run(16, 2748.12, 97.85, 377.46),
            run(32, 3721.66, 326.16, 637.79),
        ]

        selected = select_best_run(
            runs,
            max_p99_ttft_ms=100,
            max_p99_e2el_ms=400,
        )

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.concurrency, 16)

    def test_returns_none_when_every_configuration_violates_slo(self) -> None:
        selected = select_best_run(
            [run(1, 224.47, 31.33, 288.50)],
            max_p99_ttft_ms=10,
            max_p99_e2el_ms=100,
        )

        self.assertIsNone(selected)


if __name__ == "__main__":
    unittest.main()
