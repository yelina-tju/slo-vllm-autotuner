#!/usr/bin/env python3
"""Drive recovery rollback from real HTTP/SSE measurements with a slow backend."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import time

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from slo_autotuner.controller import (  # noqa: E402
    AdaptiveServingController,
    ControllerConfig,
    RollingWorkloadDetector,
    load_policy_catalog,
)
from slo_autotuner.executor import AdmissionGate, PolicyExecutor  # noqa: E402
from slo_autotuner.gateway import GatewayRuntime  # noqa: E402


class TokenListTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        if add_special_tokens:
            raise AssertionError("special tokens are not expected")
        return [int(piece) for piece in text.split()]


class NoRestartLifecycle:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def stop(self) -> tuple[bool, str]:
        self.calls.append("stop")
        return True, "stopped"

    async def start(self, _policy) -> tuple[bool, str]:
        self.calls.append("start")
        return True, "started"

    async def wait_healthy(self, _timeout_s: float) -> tuple[bool, str]:
        self.calls.append("health")
        return True, "healthy"

    async def warm_up(self, _policy) -> tuple[bool, str]:
        self.calls.append("warmup")
        return True, "warmed"


def build_controller(enabled: bool) -> AdaptiveServingController:
    config = ControllerConfig.from_json(PROJECT_ROOT / "configs" / "controller.json")
    config = replace(
        config,
        compatible_recovery_rollback_enabled=enabled,
        compatible_recovery_canary_admission_limits_rps=(),
    )
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
    controller = AdaptiveServingController(config, catalog, detector)
    mixed = catalog.primary_for(config.mixed_profile_name)
    controller.force_active_policy(mixed.name, 0, 0)
    return controller


async def slow_backend() -> web.Application:
    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def completion(_request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            status=200,
            headers={"Content-Type": "text/event-stream"},
        )
        await response.prepare(_request)
        await asyncio.sleep(0.12)
        await response.write(
            b'data: {"choices":[{"token_ids":[42],"text":""}]}\n\n'
        )
        await asyncio.sleep(0.32)
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/v1/completions", completion)
    return app


async def issue_batch(client: TestClient, count: int) -> list[int]:
    async def one() -> int:
        response = await client.post(
            "/v1/completions",
            json={
                "model": "fault-test",
                "prompt": list(range(256)),
                "max_tokens": 64,
                "stream": True,
            },
        )
        await response.read()
        return response.status

    return list(await asyncio.gather(*(one() for _ in range(count))))


async def run_mode(enabled: bool) -> dict:
    backend_server = TestServer(await slow_backend())
    await backend_server.start_server()
    controller = build_controller(enabled)
    gate = AdmissionGate(controller.active_policy.admission_limit_rps)
    lifecycle = NoRestartLifecycle()
    executor = PolicyExecutor(controller, controller.catalog, gate, lifecycle)
    runtime = GatewayRuntime(
        controller,
        gate,
        executor,
        TokenListTokenizer(),
        backend_base_url=str(backend_server.make_url("")),
        ensure_backend=False,
        adaptive_enabled=True,
    )
    gateway_client = TestClient(TestServer(runtime.create_app()))
    await gateway_client.start_server()
    try:
        # All requests reach the shape detector, including admission rejections.
        detector_statuses = await issue_batch(gateway_client, 40)
        base = time.monotonic()
        await runtime.run_control_once(base)
        if gate.rate_limit_rps != 24:
            raise RuntimeError("balanced recovery did not raise admission to 24")

        first_violation_statuses = await issue_batch(gateway_client, 12)
        await runtime.run_control_once(base + 11)
        second_violation_statuses = await issue_batch(gateway_client, 12)
        await runtime.run_control_once(base + 22)
        await runtime.run_control_once(base + 33)

        result = {
            "enabled": enabled,
            "detector_batch_statuses": dict(Counter(detector_statuses)),
            "first_violation_batch_statuses": dict(Counter(first_violation_statuses)),
            "second_violation_batch_statuses": dict(Counter(second_violation_statuses)),
            "events": [asdict(event) for event in runtime.events],
            "decisions": list(runtime.decisions),
            "executions": list(runtime.executions),
            "lifecycle_calls": lifecycle.calls,
            "final_state": controller.state_dict(),
            "final_admission": gate.snapshot(),
            "control_error": runtime.control_error,
        }
        actions = [item["action"] for item in result["executions"]]
        expected = ["switch", "rollback"] if enabled else ["switch"]
        if actions != expected:
            raise RuntimeError(f"unexpected execution actions: {actions} != {expected}")
        expected_rate = 3 if enabled else 24
        if gate.rate_limit_rps != expected_rate:
            raise RuntimeError(
                f"unexpected final admission: {gate.rate_limit_rps} != {expected_rate}"
            )
        if lifecycle.calls:
            raise RuntimeError(f"compatible transitions restarted backend: {lifecycle.calls}")
        if runtime.control_error is not None:
            raise RuntimeError(f"gateway control error: {runtime.control_error}")
        return result
    finally:
        await gateway_client.close()
        await backend_server.close()


async def main() -> int:
    enabled = await run_mode(True)
    disabled = await run_mode(False)
    payload = {
        "schema_version": 1,
        "fault": "HTTP/SSE backend delays TTFT to about 120 ms and E2E to about 440 ms",
        "balanced_slo_ms": {"ttft": 100, "e2e": 400},
        "guard_enabled": enabled,
        "guard_disabled": disabled,
        "interpretation": (
            "Real gateway measurements produce two fresh violating windows. The "
            "guarded controller executes an admission-only rollback to 3 req/s; "
            "the disabled counterfactual only alerts and remains at 24 req/s."
        ),
    }
    output = PROJECT_ROOT / "results" / "live_recovery_fault_scenario.json"
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "guard_enabled_executions": [
                    item["action"] for item in enabled["executions"]
                ],
                "guard_disabled_executions": [
                    item["action"] for item in disabled["executions"]
                ],
                "guard_enabled_final_admission": enabled["final_admission"][
                    "rate_limit_rps"
                ],
                "guard_disabled_final_admission": disabled["final_admission"][
                    "rate_limit_rps"
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
