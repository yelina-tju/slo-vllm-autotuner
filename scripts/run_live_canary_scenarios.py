#!/usr/bin/env python3
"""Exercise staged admission recovery through real HTTP/SSE gateway events."""

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


def build_controller(canary: bool) -> AdaptiveServingController:
    config = ControllerConfig.from_json(PROJECT_ROOT / "configs" / "controller.json")
    if not canary:
        config = replace(
            config,
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


def backend_app(slow: bool) -> web.Application:
    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def completion(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            status=200,
            headers={"Content-Type": "text/event-stream"},
        )
        await response.prepare(request)
        if slow:
            await asyncio.sleep(0.12)
        await response.write(
            b'data: {"choices":[{"token_ids":[42],"text":""}]}\n\n'
        )
        if slow:
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
                "model": "canary-test",
                "prompt": list(range(256)),
                "max_tokens": 64,
                "stream": True,
            },
        )
        await response.read()
        return response.status

    return list(await asyncio.gather(*(one() for _ in range(count))))


async def make_runtime(canary: bool, slow: bool):
    backend = TestServer(backend_app(slow))
    await backend.start_server()
    controller = build_controller(canary)
    gate = AdmissionGate(controller.active_policy.admission_limit_rps, burst_seconds=1)
    lifecycle = NoRestartLifecycle()
    executor = PolicyExecutor(controller, controller.catalog, gate, lifecycle)
    runtime = GatewayRuntime(
        controller,
        gate,
        executor,
        TokenListTokenizer(),
        backend_base_url=str(backend.make_url("")),
        ensure_backend=False,
        adaptive_enabled=True,
    )
    client = TestClient(TestServer(runtime.create_app()))
    await client.start_server()
    return backend, client, runtime, gate, lifecycle


def snapshot(runtime, gate, label: str) -> dict:
    return {
        "label": label,
        "admission_limit_rps": gate.rate_limit_rps,
        "active_policy": runtime.controller.active_policy_name,
        "canary_target_policy": runtime.controller.canary_target_policy_name,
        "canary_pass_count": runtime.controller.canary_pass_count,
    }


async def run_healthy_canary() -> dict:
    backend, client, runtime, gate, lifecycle = await make_runtime(True, False)
    timeline = [snapshot(runtime, gate, "initial")]
    statuses: dict[str, dict[int, int]] = {}
    try:
        statuses["detector"] = dict(Counter(await issue_batch(client, 40)))
        base = time.monotonic()
        await runtime.run_control_once(base)
        timeline.append(snapshot(runtime, gate, "recovered_to_first_canary"))

        statuses["stage8_pass1"] = dict(Counter(await issue_batch(client, 8)))
        await runtime.run_control_once(base + 11)
        timeline.append(snapshot(runtime, gate, "stage8_pass1"))
        await asyncio.sleep(1.05)
        statuses["stage8_pass2"] = dict(Counter(await issue_batch(client, 8)))
        await runtime.run_control_once(base + 22)
        timeline.append(snapshot(runtime, gate, "promoted_to_16"))

        statuses["stage16_pass1"] = dict(Counter(await issue_batch(client, 16)))
        await runtime.run_control_once(base + 33)
        timeline.append(snapshot(runtime, gate, "stage16_pass1"))
        await asyncio.sleep(1.05)
        statuses["stage16_pass2"] = dict(Counter(await issue_batch(client, 16)))
        await runtime.run_control_once(base + 44)
        timeline.append(snapshot(runtime, gate, "promoted_to_24"))

        result = collect(runtime, gate, lifecycle, timeline, statuses)
        rates = [item["admission_limit_rps"] for item in timeline]
        if rates != [3, 8, 8, 16, 16, 24]:
            decision_trace = [
                (item["action"], item["reason"])
                for item in result["decisions"]
            ]
            raise RuntimeError(
                f"unexpected healthy canary timeline: {rates}; "
                f"statuses={statuses}; decisions={decision_trace}"
            )
        if [item["action"] for item in result["executions"]] != [
            "switch", "switch", "switch"
        ]:
            raise RuntimeError("healthy canary did not execute three promotions")
        return result
    finally:
        await client.close()
        await backend.close()


async def run_slow(canary: bool) -> dict:
    backend, client, runtime, gate, lifecycle = await make_runtime(canary, True)
    timeline = [snapshot(runtime, gate, "initial")]
    statuses: dict[str, dict[int, int]] = {}
    try:
        statuses["detector"] = dict(Counter(await issue_batch(client, 40)))
        base = time.monotonic()
        await runtime.run_control_once(base)
        timeline.append(snapshot(runtime, gate, "capacity_recovery"))
        statuses["violation1"] = dict(Counter(await issue_batch(client, 24)))
        await runtime.run_control_once(base + 11)
        timeline.append(snapshot(runtime, gate, "violation1"))
        await asyncio.sleep(1.05)
        statuses["violation2"] = dict(Counter(await issue_batch(client, 24)))
        await runtime.run_control_once(base + 22)
        timeline.append(snapshot(runtime, gate, "rolled_back"))
        await runtime.run_control_once(base + 33)
        timeline.append(snapshot(runtime, gate, "retry_blocked"))

        result = collect(runtime, gate, lifecycle, timeline, statuses)
        expected_peak = 8 if canary else 24
        rates = [item["admission_limit_rps"] for item in timeline]
        if rates != [3, expected_peak, expected_peak, 3, 3]:
            raise RuntimeError(f"unexpected slow timeline: {rates}")
        if [item["action"] for item in result["executions"]] != [
            "switch", "rollback"
        ]:
            raise RuntimeError("slow scenario did not recover then roll back")
        result["slow_requests_exposed"] = sum(
            counts.get(200, 0)
            for name, counts in statuses.items()
            if name.startswith("violation")
        )
        return result
    finally:
        await client.close()
        await backend.close()


def collect(runtime, gate, lifecycle, timeline, statuses) -> dict:
    if lifecycle.calls:
        raise RuntimeError(f"canary path restarted backend: {lifecycle.calls}")
    if runtime.control_error is not None:
        raise RuntimeError(f"gateway control error: {runtime.control_error}")
    return {
        "timeline": timeline,
        "batch_statuses": statuses,
        "events": [asdict(event) for event in runtime.events],
        "decisions": list(runtime.decisions),
        "executions": list(runtime.executions),
        "lifecycle_calls": lifecycle.calls,
        "final_state": runtime.controller.state_dict(),
        "final_admission": gate.snapshot(),
        "control_error": runtime.control_error,
    }


async def main() -> int:
    healthy = await run_healthy_canary()
    slow_canary = await run_slow(True)
    slow_binary = await run_slow(False)
    if slow_canary["slow_requests_exposed"] != 16:
        raise RuntimeError("canary should expose exactly 16 slow requests")
    if slow_binary["slow_requests_exposed"] != 48:
        raise RuntimeError("binary recovery should expose exactly 48 slow requests")
    payload = {
        "schema_version": 1,
        "canary_stages_rps": [3, 8, 16, 24],
        "promotion_rule": "two SLO-pass windows with fresh successful request IDs",
        "healthy_canary": healthy,
        "slow_canary": slow_canary,
        "slow_binary": slow_binary,
        "slow_request_exposure_reduction": {
            "canary": slow_canary["slow_requests_exposed"],
            "binary": slow_binary["slow_requests_exposed"],
            "absolute": slow_binary["slow_requests_exposed"]
            - slow_canary["slow_requests_exposed"],
            "relative": 1
            - slow_canary["slow_requests_exposed"]
            / slow_binary["slow_requests_exposed"],
        },
        "interpretation": (
            "Healthy traffic reaches 24 req/s through 8 and 16. Under identical "
            "slow HTTP/SSE faults, canary caps the first exposure at 8 req/s and "
            "rolls back after 16 slow requests, versus 48 after binary recovery."
        ),
    }
    output = PROJECT_ROOT / "results" / "live_canary_scenarios.json"
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "healthy_rates": [
                    item["admission_limit_rps"]
                    for item in healthy["timeline"]
                ],
                "slow_canary_rates": [
                    item["admission_limit_rps"]
                    for item in slow_canary["timeline"]
                ],
                "slow_binary_rates": [
                    item["admission_limit_rps"]
                    for item in slow_binary["timeline"]
                ],
                "slow_request_exposure_reduction": payload[
                    "slow_request_exposure_reduction"
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
