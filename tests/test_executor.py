import asyncio
from collections import deque
from pathlib import Path
import unittest

from slo_autotuner.controller import (
    AdaptiveServingController,
    ClassWindowMetrics,
    ControllerConfig,
    RequestObservation,
    RollingWorkloadDetector,
    ServingPolicy,
    load_policy_catalog,
)
from slo_autotuner.executor import AdmissionGate, PolicyExecutor, ShellServerLifecycle


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


def switch_decision(
    controller: AdaptiveServingController,
    input_tokens: int,
    output_tokens: int = 64,
):
    for index in range(60):
        if input_tokens == 2048:
            current_input = 2048 if index % 5 == 4 else 256
        else:
            current_input = input_tokens
        controller.observe_request(
            RequestObservation(index, current_input, output_tokens)
        )
    controller.tick(60)
    controller.tick(70)
    decision = controller.tick(80)
    if decision.action != "switch":
        raise AssertionError(f"expected switch, got {decision}")
    return decision


class FakeLifecycle:
    def __init__(
        self,
        health_results: list[bool] | None = None,
        stop_results: list[bool] | None = None,
        start_results: list[bool] | None = None,
        warmup_results: list[bool] | None = None,
    ) -> None:
        self.health_results = deque(health_results or [True])
        self.stop_results = deque(stop_results or [True])
        self.start_results = deque(start_results or [True])
        self.warmup_results = deque(warmup_results or [True])
        self.calls: list[tuple[str, str | None]] = []

    async def stop(self) -> tuple[bool, str]:
        self.calls.append(("stop", None))
        result = self.stop_results.popleft() if self.stop_results else True
        return result, f"stop={result}"

    async def start(self, policy: ServingPolicy) -> tuple[bool, str]:
        self.calls.append(("start", policy.name))
        result = self.start_results.popleft() if self.start_results else True
        return result, f"start={result} policy={policy.name}"

    async def wait_healthy(self, _timeout_s: float) -> tuple[bool, str]:
        self.calls.append(("health", None))
        result = self.health_results.popleft() if self.health_results else True
        return result, f"health={result}"

    async def warm_up(self, policy: ServingPolicy) -> tuple[bool, str]:
        self.calls.append(("warmup", policy.name))
        result = self.warmup_results.popleft() if self.warmup_results else True
        return result, f"warmup={result} policy={policy.name}"


class CapturingShellLifecycle(ShellServerLifecycle):
    def __init__(self) -> None:
        super().__init__(
            PROJECT_ROOT,
            Path("/models/qwen-7b"),
            Path("/env/bin/vllm"),
            served_model_name="qwen2.5-7b",
        )
        self.captured: tuple[str, dict[str, str] | None] | None = None

    async def _run_ctl(
        self,
        action: str,
        environment: dict[str, str] | None = None,
    ) -> tuple[bool, str]:
        self.captured = (action, environment)
        return True, "captured"


class PolicyExecutorTest(unittest.IsolatedAsyncioTestCase):
    async def test_shell_lifecycle_propagates_served_model_name(self) -> None:
        lifecycle = CapturingShellLifecycle()
        policy = configured_controller().active_policy

        result = await lifecycle.start(policy)

        self.assertEqual(result, (True, "captured"))
        assert lifecycle.captured is not None
        action, environment = lifecycle.captured
        self.assertEqual(action, "start")
        assert environment is not None
        self.assertEqual(environment["SERVED_MODEL_NAME"], "qwen2.5-7b")
        self.assertEqual(environment["MODEL_PATH"], str(Path("/models/qwen-7b")))

    async def test_restart_waits_for_drain_then_resumes_target(self) -> None:
        controller = configured_controller()
        source_name = controller.active_policy_name
        decision = switch_decision(controller, input_tokens=2048)
        gate = AdmissionGate(24, burst_seconds=1)
        await gate.acquire()
        lifecycle = FakeLifecycle(health_results=[True])
        executor = PolicyExecutor(
            controller,
            controller.catalog,
            gate,
            lifecycle,
            drain_timeout_s=1,
            startup_timeout_s=1,
        )

        async def finish_request() -> None:
            await asyncio.sleep(0.01)
            await gate.release()

        release_task = asyncio.create_task(finish_request())
        result = await executor.execute(decision)
        await release_task

        self.assertEqual(result.status, "applied")
        self.assertNotEqual(result.active_policy, source_name)
        self.assertEqual(
            [name for name, _ in lifecycle.calls], ["stop", "start", "health", "warmup"]
        )
        self.assertEqual(
            result.steps,
            (
                "admission_paused",
                "in_flight_drained",
                "source_stopped",
                "target_start_command_succeeded",
                "target_health_passed",
                "target_warmup_passed",
                "target_admission_resumed",
            ),
        )
        self.assertFalse(gate.paused)
        self.assertEqual(gate.rate_limit_rps, 3)

    async def test_target_startup_failure_restores_last_working_policy(self) -> None:
        controller = configured_controller()
        source_name = controller.active_policy_name
        source_rate = controller.active_policy.admission_limit_rps
        decision = switch_decision(controller, input_tokens=2048)
        gate = AdmissionGate(source_rate)
        lifecycle = FakeLifecycle(
            health_results=[False, True],
            stop_results=[True, True],
            start_results=[True, True],
        )
        executor = PolicyExecutor(
            controller,
            controller.catalog,
            gate,
            lifecycle,
            startup_timeout_s=0.01,
        )

        result = await executor.execute(decision)

        self.assertEqual(result.status, "startup_failed_rolled_back")
        self.assertEqual(controller.active_policy_name, source_name)
        self.assertEqual(result.active_policy, source_name)
        self.assertFalse(gate.paused)
        self.assertEqual(gate.rate_limit_rps, source_rate)
        self.assertEqual(
            [name for name, _ in lifecycle.calls],
            ["stop", "start", "health", "stop", "start", "health", "warmup"],
        )

    async def test_target_warmup_failure_rolls_back_before_admission_resumes(self) -> None:
        controller = configured_controller()
        source_name = controller.active_policy_name
        decision = switch_decision(controller, input_tokens=2048)
        gate = AdmissionGate(24)
        lifecycle = FakeLifecycle(
            health_results=[True, True],
            stop_results=[True, True],
            start_results=[True, True],
            warmup_results=[False, True],
        )
        executor = PolicyExecutor(controller, controller.catalog, gate, lifecycle)

        result = await executor.execute(decision)

        self.assertEqual(result.status, "startup_failed_rolled_back")
        self.assertEqual(result.active_policy, source_name)
        self.assertTrue(result.admission_resumed)
        self.assertIn("target_warmup_failed", result.steps)
        self.assertIn("source_warmup_passed", result.steps)
        self.assertEqual(
            [name for name, _ in lifecycle.calls],
            ["stop", "start", "health", "warmup", "stop", "start", "health", "warmup"],
        )

    async def test_both_startups_fail_keeps_admission_paused(self) -> None:
        controller = configured_controller()
        source_name = controller.active_policy_name
        decision = switch_decision(controller, input_tokens=2048)
        gate = AdmissionGate(24)
        lifecycle = FakeLifecycle(
            health_results=[False, False],
            stop_results=[True, True],
            start_results=[True, True],
        )
        executor = PolicyExecutor(
            controller,
            controller.catalog,
            gate,
            lifecycle,
            startup_timeout_s=0.01,
        )

        result = await executor.execute(decision)

        self.assertEqual(result.status, "startup_and_rollback_failed")
        self.assertEqual(controller.active_policy_name, source_name)
        self.assertTrue(gate.paused)
        self.assertFalse(result.admission_resumed)

    async def test_drain_timeout_preserves_running_server(self) -> None:
        controller = configured_controller()
        source_name = controller.active_policy_name
        decision = switch_decision(controller, input_tokens=2048)
        gate = AdmissionGate(24)
        await gate.acquire()
        lifecycle = FakeLifecycle()
        executor = PolicyExecutor(
            controller,
            controller.catalog,
            gate,
            lifecycle,
            drain_timeout_s=0.01,
        )

        result = await executor.execute(decision)

        self.assertEqual(result.status, "drain_timeout")
        self.assertEqual(controller.active_policy_name, source_name)
        self.assertEqual(lifecycle.calls, [])
        self.assertFalse(gate.paused)
        await gate.release()

    async def test_same_server_configuration_only_updates_admission(self) -> None:
        controller = configured_controller()
        decision = switch_decision(controller, input_tokens=1024)
        self.assertFalse(decision.requires_server_restart)
        gate = AdmissionGate(24)
        lifecycle = FakeLifecycle()
        executor = PolicyExecutor(controller, controller.catalog, gate, lifecycle)

        result = await executor.execute(decision)

        self.assertEqual(result.status, "applied")
        self.assertEqual(lifecycle.calls, [])
        self.assertEqual(gate.rate_limit_rps, 3)
        self.assertFalse(gate.paused)

    async def test_fast_recovery_slo_rollback_reduces_admission_without_restart(self) -> None:
        controller = configured_controller()
        mixed = controller.catalog.primary_for("mixed_80_20")
        controller.force_active_policy(mixed.name, 0, 0)
        for index in range(60):
            controller.observe_request(RequestObservation(index, 256, 64))
        recovery = controller.tick(60)
        gate = AdmissionGate(3)
        lifecycle = FakeLifecycle()
        executor = PolicyExecutor(controller, controller.catalog, gate, lifecycle)

        recovered = await executor.execute(recovery)
        self.assertEqual(recovered.status, "applied")
        self.assertEqual(gate.rate_limit_rps, 8)

        controller.report_slo_window(
            70,
            {"balanced": ClassWindowMetrics(40, 0, 120, 430, (4001,))},
        )
        decision = controller.report_slo_window(
            80,
            {"balanced": ClassWindowMetrics(40, 0, 125, 440, (4001, 4002))},
        )
        rolled_back = await executor.execute(decision)

        self.assertEqual(rolled_back.status, "applied")
        self.assertEqual(rolled_back.action, "rollback")
        self.assertEqual(gate.rate_limit_rps, 3)
        self.assertEqual(lifecycle.calls, [])
        self.assertFalse(gate.paused)

    async def test_failed_admission_rollback_preserves_target_for_retry(self) -> None:
        controller = configured_controller()
        mixed = controller.catalog.primary_for("mixed_80_20")
        controller.force_active_policy(mixed.name, 0, 0)
        for index in range(60):
            controller.observe_request(RequestObservation(index, 256, 64))
        controller.tick(60)
        controller.report_slo_window(
            70,
            {"balanced": ClassWindowMetrics(40, 0, 120, 430, (6001,))},
        )
        rollback = controller.report_slo_window(
            80,
            {"balanced": ClassWindowMetrics(40, 0, 125, 440, (6001, 6002))},
        )
        gate = AdmissionGate(8)
        await gate.acquire()
        executor = PolicyExecutor(
            controller,
            controller.catalog,
            gate,
            FakeLifecycle(),
            drain_timeout_s=0.01,
        )

        result = await executor.execute(rollback)

        self.assertEqual(result.status, "drain_timeout")
        self.assertEqual(controller.active_profile, "balanced")
        self.assertEqual(controller.recovery_rollback_policy_name, mixed.name)
        self.assertFalse(gate.paused)
        self.assertEqual(gate.rate_limit_rps, 8)
        await gate.release()


if __name__ == "__main__":
    unittest.main()
