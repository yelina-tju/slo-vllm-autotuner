from dataclasses import replace
from pathlib import Path
import unittest

from slo_autotuner.controller import (
    AdaptiveServingController,
    ClassWindowMetrics,
    ControllerConfig,
    DetectorSnapshot,
    RequestObservation,
    RollingWorkloadDetector,
    evaluate_policy_slo,
    load_policy_catalog,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def configured_controller() -> AdaptiveServingController:
    config = ControllerConfig.from_json(PROJECT_ROOT / "configs" / "controller.json")
    catalog = load_policy_catalog(
        PROJECT_ROOT / "results" / "workload_policy.json",
        PROJECT_ROOT / "configs" / "workload_profiles.json",
        PROJECT_ROOT / "results" / "mixed_policy.json",
        config.mixed_profile_name,
        config.default_max_num_seqs,
    )
    detector = RollingWorkloadDetector(
        config.rolling_window_seconds,
        config.minimum_samples,
        config.shape_prototypes,
        config.profile_distributions,
    )
    return AdaptiveServingController(config, catalog, detector)


def feed_mixed(controller: AdaptiveServingController, count: int = 60) -> None:
    for index in range(count):
        is_long = index % 5 == 4
        controller.observe_request(
            RequestObservation(
                timestamp_s=index,
                input_tokens=2048 if is_long else 256,
                output_tokens=64,
            )
        )


class ControllerTest(unittest.TestCase):
    def test_detector_recognizes_exact_mixed_distribution(self) -> None:
        controller = configured_controller()
        feed_mixed(controller)

        snapshot = controller.detector.snapshot(60)

        self.assertEqual(snapshot.best_profile, "mixed_80_20")
        self.assertAlmostEqual(snapshot.best_distance or 0, 0)
        self.assertEqual(snapshot.distribution["prefill_heavy"], 0.2)

    def test_hysteresis_rejects_a_small_distribution_advantage(self) -> None:
        controller = configured_controller()
        for index in range(60):
            is_long = index >= 52
            controller.observe_request(
                RequestObservation(
                    timestamp_s=index,
                    input_tokens=1024 if is_long else 256,
                    output_tokens=64,
                )
            )

        decision = controller.tick(60)

        self.assertEqual(decision.action, "hold")
        self.assertIsNone(decision.pending_profile)
        self.assertIn("hysteresis", decision.reason)

    def test_switch_confirmation_then_slo_rollback_bypasses_cooldown(self) -> None:
        controller = configured_controller()
        feed_mixed(controller)

        self.assertEqual(controller.tick(60).action, "hold")
        self.assertEqual(controller.tick(70).action, "hold")
        switched = controller.tick(80)
        self.assertEqual(switched.action, "switch")
        self.assertEqual(controller.active_profile, "mixed_80_20")
        self.assertEqual(switched.admission_limit_rps, 3)
        self.assertEqual(switched.server_environment["MAX_NUM_BATCHED_TOKENS"], "1024")
        self.assertTrue(switched.requires_server_restart)
        primary = controller.active_policy_name

        violating = {
            "interactive_short": ClassWindowMetrics(40, 0, 90, 430, (1,)),
            "document_long": ClassWindowMetrics(10, 0, 150, 450),
        }
        first = controller.report_slo_window(81, violating)
        violating_with_fresh_evidence = {
            "interactive_short": ClassWindowMetrics(41, 0, 90, 430, (1, 2)),
            "document_long": ClassWindowMetrics(10, 0, 150, 450),
        }
        second = controller.report_slo_window(82, violating_with_fresh_evidence)

        self.assertEqual(first.action, "hold")
        self.assertEqual(second.action, "rollback")
        self.assertEqual(second.server_environment["MAX_NUM_BATCHED_TOKENS"], "2048")
        self.assertTrue(second.requires_server_restart)
        self.assertNotEqual(controller.active_policy_name, primary)
        self.assertIn("rollback", controller.active_policy_name)

    def test_overlapping_window_cannot_reuse_one_bad_request_to_confirm_rollback(self) -> None:
        controller = configured_controller()
        feed_mixed(controller)
        controller.tick(60)
        controller.tick(70)
        controller.tick(80)
        same_evidence = {
            "interactive_short": ClassWindowMetrics(40, 0, 120, 430, (1732,)),
            "document_long": ClassWindowMetrics(10, 0, 150, 450),
        }

        first = controller.report_slo_window(81, same_evidence)
        second = controller.report_slo_window(91, same_evidence)

        self.assertEqual(first.action, "hold")
        self.assertEqual(second.action, "hold")
        self.assertIn("no new violating requests", second.reason)
        self.assertEqual(controller.consecutive_slo_violations, 1)

    def test_admission_only_recovery_can_bypass_restart_cooldown(self) -> None:
        controller = configured_controller()
        rollback = controller.catalog.rollback_for("mixed_80_20")
        assert rollback is not None
        controller.force_active_policy(rollback.name, 100, 300)
        for index in range(60):
            controller.observe_request(RequestObservation(100 + index, 256, 64))

        recovered = controller.tick(160)

        self.assertEqual(recovered.action, "switch")
        self.assertFalse(recovered.requires_server_restart)
        self.assertEqual(recovered.admission_limit_rps, 8)
        self.assertEqual(controller.active_profile, "balanced")

    def test_mixed_primary_can_recover_through_compatible_balanced_policy(self) -> None:
        controller = configured_controller()
        mixed = controller.catalog.primary_for("mixed_80_20")
        controller.force_active_policy(mixed.name, 100, 300)
        for index in range(60):
            controller.observe_request(RequestObservation(100 + index, 256, 64))

        recovered = controller.tick(160)

        self.assertEqual(recovered.action, "switch")
        self.assertFalse(recovered.requires_server_restart)
        self.assertEqual(recovered.admission_limit_rps, 8)
        self.assertEqual(
            recovered.server_environment["MAX_NUM_BATCHED_TOKENS"], "1024"
        )
        self.assertIn("mbt1024-seq256", recovered.to_policy)

    def test_canary_promotes_only_on_fresh_passing_windows(self) -> None:
        controller = configured_controller()
        mixed = controller.catalog.primary_for("mixed_80_20")
        controller.force_active_policy(mixed.name, 0, 0)
        for index in range(60):
            controller.observe_request(RequestObservation(index, 256, 64))

        first_stage = controller.tick(60)
        self.assertEqual(first_stage.admission_limit_rps, 8)
        self.assertIsNotNone(controller.canary_target_policy_name)
        passing = {
            "balanced": ClassWindowMetrics(
                6, 0, 80, 350, (), tuple(range(7001, 7007))
            )
        }
        first_pass = controller.report_slo_window(70, passing)
        reused_pass = controller.report_slo_window(80, passing)
        fresh_pass = controller.report_slo_window(
            90,
            {
                "balanced": ClassWindowMetrics(
                    7, 0, 80, 350, (), tuple(range(7001, 7008))
                )
            },
        )

        self.assertEqual(first_pass.action, "hold")
        self.assertIn("awaiting promotion", first_pass.reason)
        self.assertEqual(reused_pass.action, "hold")
        self.assertIn("no new successful requests", reused_pass.reason)
        self.assertEqual(fresh_pass.action, "switch")
        self.assertEqual(fresh_pass.admission_limit_rps, 16)
        self.assertFalse(fresh_pass.requires_server_restart)

        controller.report_slo_window(
            100,
            {
                "balanced": ClassWindowMetrics(
                    6, 0, 80, 350, (), tuple(range(7101, 7107))
                )
            },
        )
        final_stage = controller.report_slo_window(
            110,
            {
                "balanced": ClassWindowMetrics(
                    7, 0, 80, 350, (), tuple(range(7101, 7108))
                )
            },
        )

        self.assertEqual(final_stage.action, "switch")
        self.assertEqual(final_stage.admission_limit_rps, 24)
        self.assertIsNone(controller.canary_target_policy_name)
        self.assertIn("canary", first_stage.to_policy)
        self.assertIn("canary", fresh_pass.to_policy)
        self.assertNotIn("canary", final_stage.to_policy)

    def test_canary_violation_rolls_back_one_verified_stage(self) -> None:
        controller = configured_controller()
        mixed = controller.catalog.primary_for("mixed_80_20")
        controller.force_active_policy(mixed.name, 0, 0)
        for index in range(60):
            controller.observe_request(RequestObservation(index, 256, 64))
        stage_8 = controller.tick(60)
        controller.report_slo_window(
            70,
            {"balanced": ClassWindowMetrics(6, 0, 80, 350, (), (7201,))},
        )
        stage_16 = controller.report_slo_window(
            80,
            {"balanced": ClassWindowMetrics(7, 0, 80, 350, (), (7201, 7202))},
        )
        self.assertEqual(stage_16.admission_limit_rps, 16)

        controller.report_slo_window(
            90,
            {"balanced": ClassWindowMetrics(8, 0, 120, 430, (7301,))},
        )
        rollback = controller.report_slo_window(
            100,
            {"balanced": ClassWindowMetrics(8, 0, 125, 440, (7301, 7302))},
        )

        self.assertEqual(rollback.action, "rollback")
        self.assertFalse(rollback.requires_server_restart)
        self.assertEqual(rollback.admission_limit_rps, 8)
        self.assertEqual(rollback.to_policy, stage_8.to_policy)
        self.assertIsNone(controller.canary_target_policy_name)

    def test_compatible_recovery_uses_relaxed_margin_and_one_confirmation(self) -> None:
        controller = configured_controller()
        snapshot = DetectorSnapshot(
            timestamp_s=100,
            sample_count=60,
            estimated_rps=1,
            distribution={
                "balanced": 0.91,
                "prefill_heavy": 0.09,
                "decode_heavy": 0.0,
            },
            profile_distances={
                "balanced": 0.09,
                "mixed_80_20": 0.10,
                "prefill_heavy_4x": 0.91,
                "decode_heavy_4x": 1.0,
            },
            best_profile="balanced",
            best_distance=0.09,
            status="ready",
        )

        class FixedDetector:
            def snapshot(self, now_s: float) -> DetectorSnapshot:
                return snapshot

        mixed = controller.catalog.primary_for("mixed_80_20")
        controller.force_active_policy(mixed.name, 0, 300)
        controller.detector = FixedDetector()  # type: ignore[assignment]

        recovered = controller.tick(100)

        self.assertEqual(recovered.action, "switch")
        self.assertFalse(recovered.requires_server_restart)
        self.assertEqual(recovered.active_profile, "balanced")

    def test_compatible_recovery_slo_failure_rolls_back_and_blocks_retry(self) -> None:
        controller = configured_controller()
        mixed = controller.catalog.primary_for("mixed_80_20")
        controller.force_active_policy(mixed.name, 0, 0)
        for index in range(60):
            controller.observe_request(RequestObservation(index, 256, 64))

        recovered = controller.tick(60)
        self.assertEqual(recovered.action, "switch")
        self.assertFalse(recovered.requires_server_restart)
        self.assertEqual(controller.recovery_rollback_policy_name, mixed.name)

        first = controller.report_slo_window(
            70,
            {"balanced": ClassWindowMetrics(40, 0, 120, 430, (2001,))},
        )
        second = controller.report_slo_window(
            80,
            {"balanced": ClassWindowMetrics(40, 0, 125, 440, (2001, 2002))},
        )

        self.assertEqual(first.action, "hold")
        self.assertEqual(second.action, "rollback")
        self.assertFalse(second.requires_server_restart)
        self.assertEqual(controller.active_profile, "mixed_80_20")
        self.assertEqual(controller.active_policy_name, mixed.name)
        self.assertEqual(controller.active_policy.admission_limit_rps, 3)
        blocked = controller.tick(90)
        self.assertEqual(blocked.action, "hold")
        self.assertIn("capacity-increase recovery cooldown", blocked.reason)

    def test_disabling_recovery_rollback_reproduces_alert_only_gap(self) -> None:
        controller = configured_controller()
        controller.config = replace(
            controller.config,
            compatible_recovery_rollback_enabled=False,
            compatible_recovery_canary_admission_limits_rps=(),
        )
        mixed = controller.catalog.primary_for("mixed_80_20")
        controller.force_active_policy(mixed.name, 0, 0)
        for index in range(60):
            controller.observe_request(RequestObservation(index, 256, 64))
        self.assertEqual(controller.tick(60).action, "switch")

        controller.report_slo_window(
            70,
            {"balanced": ClassWindowMetrics(40, 0, 120, 430, (3001,))},
        )
        second = controller.report_slo_window(
            80,
            {"balanced": ClassWindowMetrics(40, 0, 125, 440, (3001, 3002))},
        )

        self.assertEqual(second.action, "alert")
        self.assertEqual(controller.active_profile, "balanced")

    def test_normal_profile_change_is_blocked_during_cooldown(self) -> None:
        controller = configured_controller()
        feed_mixed(controller)
        controller.tick(60)
        controller.tick(70)
        controller.tick(80)
        for index in range(60):
            controller.observe_request(
                RequestObservation(100 + index, 256, 256)
            )

        decision = controller.tick(160)

        self.assertEqual(decision.action, "hold")
        self.assertIn("cooldown", decision.reason)
        self.assertEqual(controller.active_profile, "mixed_80_20")

    def test_oracle_profile_decision_bypasses_detector_and_reports_restart(self) -> None:
        controller = configured_controller()

        to_mixed = controller.force_profile_decision("mixed_80_20", 60)
        to_balanced = controller.force_profile_decision("balanced", 210)

        self.assertEqual(to_mixed.action, "switch")
        self.assertTrue(to_mixed.requires_server_restart)
        self.assertEqual(to_mixed.admission_limit_rps, 3)
        self.assertEqual(to_balanced.action, "switch")
        self.assertFalse(to_balanced.requires_server_restart)
        self.assertEqual(to_balanced.admission_limit_rps, 24)
        self.assertIn("mbt1024-seq256", to_balanced.to_policy)

    def test_missing_class_metrics_are_not_treated_as_pass_or_failure(self) -> None:
        controller = configured_controller()
        feed_mixed(controller)
        controller.tick(60)
        controller.tick(70)
        controller.tick(80)

        evaluation = evaluate_policy_slo(
            controller.active_policy,
            {
                "interactive_short": ClassWindowMetrics(40, 0, 80, 380),
            },
            minimum_samples_per_class=5,
        )

        self.assertEqual(evaluation.status, "insufficient_samples")

    def test_sparse_failed_request_is_still_an_slo_violation(self) -> None:
        controller = configured_controller()
        evaluation = evaluate_policy_slo(
            controller.active_policy,
            {"balanced": ClassWindowMetrics(0, 1, 0, 0)},
            minimum_samples_per_class=5,
        )

        self.assertEqual(evaluation.status, "violation")
        self.assertIn("failed requests", evaluation.reasons[0])

    def test_catalog_uses_generated_selected_and_rollback_policies(self) -> None:
        controller = configured_controller()
        bundle = controller.catalog.bundles["mixed_80_20"]

        self.assertIn("mbt1024_fcfs", bundle.primary_policy)
        self.assertIsNotNone(bundle.rollback_policy)
        assert bundle.rollback_policy is not None
        self.assertIn("mbt2048_fcfs", bundle.rollback_policy)


if __name__ == "__main__":
    unittest.main()
