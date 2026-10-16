from pathlib import Path
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from slo_autotuner.controller import (
    AdaptiveServingController,
    ControllerConfig,
    RequestObservation,
    RollingWorkloadDetector,
    ServingPolicy,
    load_policy_catalog,
)
from slo_autotuner.executor import AdmissionGate, PolicyExecutor
from slo_autotuner.gateway import (
    CompletedRequest,
    CompletionSseTracker,
    GatewayRuntime,
    PromptTokenCounter,
    RollingSloCollector,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DummyTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        if add_special_tokens:
            raise AssertionError("gateway must not add special tokens")
        return text.split()


class FakeLifecycle:
    def __init__(self, warmup_result: bool = True) -> None:
        self.calls: list[str] = []
        self.warmup_result = warmup_result

    async def stop(self) -> tuple[bool, str]:
        self.calls.append("stop")
        return True, "stopped"

    async def start(self, _policy: ServingPolicy) -> tuple[bool, str]:
        self.calls.append("start")
        return True, "started"

    async def wait_healthy(self, _timeout_s: float) -> tuple[bool, str]:
        self.calls.append("health")
        return True, "healthy"

    async def warm_up(self, _policy: ServingPolicy) -> tuple[bool, str]:
        self.calls.append("warmup")
        return self.warmup_result, f"warmed={self.warmup_result}"


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


class GatewayUnitTest(unittest.TestCase):
    def test_sse_tracker_handles_a_json_line_split_between_chunks(self) -> None:
        tracker = CompletionSseTracker()
        self.assertFalse(tracker.feed(b'data: {"choices":[{"token_'))
        self.assertTrue(
            tracker.feed(b'ids":[151645],"text":""}]}\r\n\r\ndata: [DONE]\n\n')
        )
        self.assertTrue(tracker.seen_token)
        self.assertTrue(tracker.seen_done)

    def test_prompt_counter_handles_text_and_exact_token_ids(self) -> None:
        counter = PromptTokenCounter(DummyTokenizer())
        self.assertEqual(counter.request_shape({"prompt": "a b c", "max_tokens": 4}), (3, 4))
        self.assertEqual(counter.request_shape({"prompt": [1, 2, 3], "max_tokens": 5}), (3, 5))
        with self.assertRaises(ValueError):
            counter.request_shape({"prompt": [[1, 2]], "max_tokens": 5})

    def test_collector_maps_mixed_shapes_to_independent_slo_classes(self) -> None:
        controller = configured_controller()
        collector = RollingSloCollector(
            60,
            controller.config.slo_class_mapping,
        )
        collector.record(CompletedRequest(10, "balanced", 50, 300, True, 1))
        collector.record(CompletedRequest(11, "prefill_heavy", 100, 450, True, 2))
        collector.record(CompletedRequest(12, "prefill_heavy", None, 1, False, 3))
        policy = controller.catalog.primary_for("mixed_80_20")

        metrics = collector.metrics_for(policy, 12)

        self.assertEqual(metrics["interactive_short"].completed, 1)
        self.assertEqual(metrics["interactive_short"].failed, 0)
        self.assertEqual(metrics["document_long"].completed, 1)
        self.assertEqual(metrics["document_long"].failed, 1)
        self.assertEqual(metrics["document_long"].violating_request_ids, (3,))
        self.assertEqual(metrics["interactive_short"].successful_request_ids, (1,))
        self.assertEqual(metrics["document_long"].successful_request_ids, (2,))


class GatewayIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.backend_payloads: list[dict] = []

        async def health(_request: web.Request) -> web.Response:
            return web.json_response({"status": "ok"})

        async def completions(request: web.Request) -> web.StreamResponse:
            self.backend_payloads.append(await request.json())
            response = web.StreamResponse(
                status=200, headers={"Content-Type": "text/event-stream"}
            )
            await response.prepare(request)
            await response.write(b'data: {"choices":[{"token_')
            await response.write(b'ids":[42],"text":""}]}\n\n')
            await response.write(b"data: [DONE]\n\n")
            await response.write_eof()
            return response

        backend_app = web.Application()
        backend_app.router.add_get("/health", health)
        backend_app.router.add_post("/v1/completions", completions)
        self.backend_server = TestServer(backend_app)
        await self.backend_server.start_server()

        controller = configured_controller()
        gate = AdmissionGate(controller.active_policy.admission_limit_rps)
        lifecycle = FakeLifecycle()
        executor = PolicyExecutor(controller, controller.catalog, gate, lifecycle)
        self.runtime = GatewayRuntime(
            controller,
            gate,
            executor,
            DummyTokenizer(),
            backend_base_url=str(self.backend_server.make_url("")),
            ensure_backend=False,
        )
        self.gateway_client = TestClient(TestServer(self.runtime.create_app()))
        await self.gateway_client.start_server()

    async def asyncTearDown(self) -> None:
        await self.gateway_client.close()
        await self.backend_server.close()

    async def test_live_stream_is_proxied_and_recorded(self) -> None:
        response = await self.gateway_client.post(
            "/v1/completions",
            json={
                "model": "test",
                "prompt": list(range(256)),
                "max_tokens": 64,
                "stream": True,
            },
        )
        body = await response.text()

        self.assertEqual(response.status, 200)
        self.assertIn("[DONE]", body)
        self.assertTrue(self.backend_payloads[0]["return_token_ids"])
        self.assertEqual(len(self.runtime.events), 1)
        self.assertTrue(self.runtime.events[0].success)
        self.assertEqual(self.runtime.events[0].shape, "balanced")
        self.assertEqual(self.runtime.admission_gate.in_flight, 0)
        self.assertEqual(
            self.runtime.slo_collector.sample_count(
                self.runtime.events[0].completed_at_s
            ),
            1,
        )

    async def test_paused_admission_returns_503_without_backend_dispatch(self) -> None:
        await self.runtime.admission_gate.pause()
        response = await self.gateway_client.post(
            "/v1/completions",
            json={
                "model": "test",
                "prompt": [1, 2, 3],
                "max_tokens": 4,
                "stream": True,
            },
        )

        self.assertEqual(response.status, 503)
        self.assertEqual(self.backend_payloads, [])
        self.assertFalse(self.runtime.events[0].admitted)
        self.assertEqual(
            self.runtime.slo_collector.sample_count(
                self.runtime.events[0].completed_at_s
            ),
            0,
        )

    async def test_static_mode_keeps_proxy_but_never_executes_a_decision(self) -> None:
        self.runtime.adaptive_enabled = False
        await self.runtime.run_control_once()
        self.assertEqual(list(self.runtime.decisions), [])
        response = await self.gateway_client.post(
            "/v1/completions",
            json={"model": "test", "prompt": [1, 2, 3], "max_tokens": 4, "stream": True},
        )
        self.assertEqual(response.status, 200)
        await response.read()
        self.assertEqual(len(self.runtime.events), 1)

    async def test_slo_pass_canary_switch_updates_live_admission_gate(self) -> None:
        controller = self.runtime.controller
        mixed = controller.catalog.primary_for("mixed_80_20")
        controller.force_active_policy(mixed.name, 0, 0)
        await self.runtime.admission_gate.resume(3)
        for index in range(60):
            controller.observe_request(RequestObservation(index, 256, 64))

        await self.runtime.run_control_once(60)
        self.assertEqual(self.runtime.admission_gate.rate_limit_rps, 8)

        for request_id in range(8001, 8007):
            self.runtime.slo_collector.record(
                CompletedRequest(70, "balanced", 50, 300, True, request_id)
            )
        await self.runtime.run_control_once(71)
        self.assertEqual(self.runtime.admission_gate.rate_limit_rps, 8)
        self.runtime.slo_collector.record(
            CompletedRequest(80, "balanced", 50, 300, True, 8007)
        )
        await self.runtime.run_control_once(82)

        self.assertEqual(self.runtime.admission_gate.rate_limit_rps, 16)
        self.assertEqual(
            [item["action"] for item in self.runtime.executions],
            ["switch", "switch"],
        )
        self.assertEqual(self.runtime.executor.lifecycle.calls, [])


class GatewayOwnershipTest(unittest.IsolatedAsyncioTestCase):
    def build_runtime(
        self,
        lifecycle: FakeLifecycle,
        adopt_existing_backend: bool,
    ) -> GatewayRuntime:
        controller = configured_controller()
        gate = AdmissionGate(controller.active_policy.admission_limit_rps)
        executor = PolicyExecutor(controller, controller.catalog, gate, lifecycle)
        return GatewayRuntime(
            controller,
            gate,
            executor,
            DummyTokenizer(),
            ensure_backend=True,
            adopt_existing_backend=adopt_existing_backend,
        )

    async def test_default_start_replaces_unknown_existing_backend(self) -> None:
        lifecycle = FakeLifecycle()
        runtime = self.build_runtime(lifecycle, adopt_existing_backend=False)
        await runtime.start(None)  # type: ignore[arg-type]
        try:
            self.assertEqual(
                lifecycle.calls, ["health", "stop", "start", "health", "warmup"]
            )
            self.assertIn("ownership established", runtime.startup_detail)
        finally:
            await runtime.close(None)  # type: ignore[arg-type]

    async def test_explicit_adoption_trusts_healthy_existing_backend(self) -> None:
        lifecycle = FakeLifecycle()
        runtime = self.build_runtime(lifecycle, adopt_existing_backend=True)
        await runtime.start(None)  # type: ignore[arg-type]
        try:
            self.assertEqual(lifecycle.calls, ["health"])
        finally:
            await runtime.close(None)  # type: ignore[arg-type]

    async def test_initial_warmup_failure_stops_backend_and_fails_startup(self) -> None:
        lifecycle = FakeLifecycle(warmup_result=False)
        runtime = self.build_runtime(lifecycle, adopt_existing_backend=False)
        with self.assertRaisesRegex(RuntimeError, "performance warm-up failed"):
            await runtime.start(None)  # type: ignore[arg-type]
        self.assertEqual(
            lifecycle.calls,
            ["health", "stop", "start", "health", "warmup", "stop"],
        )

    async def test_static_start_does_not_create_a_control_task(self) -> None:
        runtime = self.build_runtime(FakeLifecycle(), adopt_existing_backend=False)
        runtime.adaptive_enabled = False
        await runtime.start(None)  # type: ignore[arg-type]
        try:
            self.assertIsNone(runtime._control_task)
        finally:
            await runtime.close(None)  # type: ignore[arg-type]

    async def test_transition_audit_measures_end_to_end_executor_duration(self) -> None:
        runtime = self.build_runtime(FakeLifecycle(), adopt_existing_backend=False)
        for index in range(60):
            runtime.controller.observe_request(
                RequestObservation(index, 2048 if index % 5 == 4 else 256, 64)
            )
        runtime.controller.tick(60)
        runtime.controller.tick(70)
        decision = runtime.controller.tick(80)
        self.assertEqual(decision.action, "switch")
        await runtime._execute(decision)
        event = runtime.executions[-1]
        self.assertGreaterEqual(event["completed_at_s"], event["started_at_s"])
        self.assertAlmostEqual(event["duration_s"], event["completed_at_s"] - event["started_at_s"])
        self.assertTrue(event["requires_server_restart"])
        self.assertTrue(event["admission_resumed"])
        self.assertFalse(runtime.execution_in_progress)


if __name__ == "__main__":
    unittest.main()
