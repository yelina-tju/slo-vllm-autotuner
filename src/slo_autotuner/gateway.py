"""Live OpenAI-compatible request gateway for the adaptive controller."""

from __future__ import annotations

import asyncio
import codecs
from collections import deque
from contextlib import suppress
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Any, IO, Mapping

import aiohttp
from aiohttp import web

from .controller import (
    AdaptiveServingController,
    ClassWindowMetrics,
    RequestObservation,
    ServingPolicy,
)
from .executor import AdmissionGate, AdmissionRejected, ExecutionResult, PolicyExecutor
from .mixed import completion_event_has_token, percentile


@dataclass(frozen=True)
class CompletedRequest:
    """One admitted request after the backend stream has ended."""

    completed_at_s: float
    shape: str
    ttft_ms: float | None
    e2el_ms: float
    success: bool
    request_id: int | None = None


@dataclass(frozen=True)
class RequestEvent:
    """Bounded, JSON-serializable audit event exposed by ``/events``."""

    request_id: int
    started_at_s: float
    completed_at_s: float
    input_tokens: int
    requested_output_tokens: int
    shape: str
    admitted: bool
    status_code: int
    success: bool
    ttft_ms: float | None
    e2el_ms: float
    error: str | None


class RollingSloCollector:
    """Aggregate real completed-request events into controller SLO windows."""

    def __init__(
        self,
        window_seconds: float,
        slo_class_mapping: Mapping[str, Mapping[str, str]],
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.window_seconds = window_seconds
        self.slo_class_mapping = {
            profile: dict(mapping)
            for profile, mapping in slo_class_mapping.items()
        }
        self._requests: deque[CompletedRequest] = deque()

    def record(self, request: CompletedRequest) -> None:
        self._requests.append(request)
        self._trim(request.completed_at_s)

    def clear(self) -> None:
        self._requests.clear()

    def sample_count(self, now_s: float) -> int:
        self._trim(now_s)
        return len(self._requests)

    def metrics_for(
        self,
        policy: ServingPolicy,
        now_s: float,
    ) -> dict[str, ClassWindowMetrics]:
        self._trim(now_s)
        shape_mapping = self.slo_class_mapping.get(policy.profile, {})
        metrics: dict[str, ClassWindowMetrics] = {}
        for class_name in policy.slo_limits:
            selected = [
                request
                for request in self._requests
                if shape_mapping.get(request.shape) == class_name
            ]
            if not selected:
                continue
            completed = [
                request
                for request in selected
                if request.success and request.ttft_ms is not None
            ]
            p99_ttft = percentile(
                (request.ttft_ms for request in completed if request.ttft_ms is not None),
                0.99,
            )
            p99_e2el = percentile(
                (request.e2el_ms for request in completed),
                0.99,
            )
            metrics[class_name] = ClassWindowMetrics(
                completed=len(completed),
                failed=len(selected) - len(completed),
                p99_ttft_ms=0.0 if p99_ttft is None else p99_ttft,
                p99_e2el_ms=0.0 if p99_e2el is None else p99_e2el,
                violating_request_ids=tuple(
                    request.request_id
                    for request in selected
                    if request.request_id is not None
                    and (
                        not request.success
                        or request.ttft_ms is None
                        or request.ttft_ms > policy.slo_limits[class_name].ttft_ms
                        or request.e2el_ms > policy.slo_limits[class_name].e2el_ms
                    )
                ),
                successful_request_ids=tuple(
                    request.request_id
                    for request in completed
                    if request.request_id is not None
                ),
            )
        return metrics

    def _trim(self, now_s: float) -> None:
        cutoff = now_s - self.window_seconds
        while self._requests and self._requests[0].completed_at_s < cutoff:
            self._requests.popleft()


class CompletionSseTracker:
    """Incrementally parse SSE lines even when network chunks split UTF-8/JSON."""

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buffer = ""
        self.seen_token = False
        self.seen_done = False

    def feed(self, chunk: bytes) -> bool:
        """Return true only when this chunk reveals the first generated token."""
        had_token = self.seen_token
        self._buffer += self._decoder.decode(chunk)
        self._consume_complete_lines()
        return not had_token and self.seen_token

    def finish(self) -> bool:
        had_token = self.seen_token
        self._buffer += self._decoder.decode(b"", final=True)
        if self._buffer:
            self._consume_line(self._buffer)
            self._buffer = ""
        return not had_token and self.seen_token

    def _consume_complete_lines(self) -> None:
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._consume_line(line)

    def _consume_line(self, line: str) -> None:
        line = line.rstrip("\r")
        if not line.startswith("data:"):
            return
        payload = line.removeprefix("data:").strip()
        if payload == "[DONE]":
            self.seen_done = True
            return
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return
        if completion_event_has_token(event):
            self.seen_token = True


class PromptTokenCounter:
    """Count one completion prompt without changing its backend representation."""

    def __init__(self, tokenizer: Any) -> None:
        self.tokenizer = tokenizer

    def request_shape(self, payload: Mapping[str, Any]) -> tuple[int, int]:
        prompt = payload.get("prompt")
        if isinstance(prompt, str):
            input_tokens = len(
                self.tokenizer.encode(prompt, add_special_tokens=False)
            )
        elif isinstance(prompt, list) and prompt and all(
            isinstance(token_id, int) and not isinstance(token_id, bool)
            for token_id in prompt
        ):
            input_tokens = len(prompt)
        else:
            raise ValueError(
                "the gateway currently accepts one text prompt or one token-id list"
            )

        output_tokens = payload.get("max_tokens", 16)
        if not isinstance(output_tokens, int) or isinstance(output_tokens, bool):
            raise ValueError("max_tokens must be an integer")
        if input_tokens <= 0 or output_tokens <= 0:
            raise ValueError("input and output token counts must be positive")
        return input_tokens, output_tokens


class GatewayRuntime:
    """Proxy requests, emit measurements, and execute controller decisions."""

    def __init__(
        self,
        controller: AdaptiveServingController,
        admission_gate: AdmissionGate,
        executor: PolicyExecutor,
        tokenizer: Any,
        backend_base_url: str = "http://127.0.0.1:8000",
        backend_request_timeout_s: float = 180.0,
        startup_timeout_s: float = 120.0,
        ensure_backend: bool = True,
        adopt_existing_backend: bool = False,
        event_history_size: int = 200,
        audit_path: Path | None = None,
        adaptive_enabled: bool = True,
    ) -> None:
        self.controller = controller
        self.admission_gate = admission_gate
        self.executor = executor
        self.token_counter = PromptTokenCounter(tokenizer)
        self.backend_base_url = backend_base_url.rstrip("/")
        self.backend_request_timeout_s = backend_request_timeout_s
        self.startup_timeout_s = startup_timeout_s
        self.ensure_backend = ensure_backend
        self.adopt_existing_backend = adopt_existing_backend
        self.audit_path = audit_path
        self.adaptive_enabled = adaptive_enabled
        self.slo_collector = RollingSloCollector(
            controller.config.rolling_window_seconds,
            controller.config.slo_class_mapping,
        )
        self.events: deque[RequestEvent] = deque(maxlen=event_history_size)
        self.decisions: deque[dict[str, Any]] = deque(maxlen=100)
        self.executions: deque[dict[str, Any]] = deque(maxlen=50)
        self._session: aiohttp.ClientSession | None = None
        self._control_task: asyncio.Task[None] | None = None
        self._audit_file: IO[str] | None = None
        self._next_request_id = 1
        self.execution_in_progress = False
        self.startup_detail = "not started"
        self.control_error: str | None = None

    def create_app(self) -> web.Application:
        app = web.Application(client_max_size=16 * 1024 * 1024)
        app.router.add_post("/v1/completions", self.handle_completions)
        app.router.add_get("/health", self.handle_health)
        app.router.add_get("/controller/state", self.handle_state)
        app.router.add_get("/events", self.handle_events)
        app.on_startup.append(self.start)
        app.on_cleanup.append(self.close)
        return app

    async def start(self, _app: web.Application) -> None:
        timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=10,
            sock_read=self.backend_request_timeout_s,
        )
        self._session = aiohttp.ClientSession(
            timeout=timeout,
            connector=aiohttp.TCPConnector(limit=0),
        )
        if self.audit_path is not None:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            self._audit_file = self.audit_path.open(
                "a", encoding="utf-8", buffering=1
            )
        if self.ensure_backend:
            healthy, detail = await self.executor.lifecycle.wait_healthy(2.0)
            if healthy and self.adopt_existing_backend:
                self.startup_detail = "existing backend healthy; assumed default policy"
            else:
                stopped, stop_detail = await self.executor.lifecycle.stop()
                if not stopped:
                    await self._close_resources()
                    raise RuntimeError(
                        "could not establish ownership of initial backend: "
                        f"{stop_detail}; initial probe: {detail}"
                    )
                started, start_detail = await self.executor.lifecycle.start(
                    self.controller.active_policy
                )
                if not started:
                    await self._close_resources()
                    raise RuntimeError(f"initial backend start failed: {start_detail}")
                healthy, health_detail = await self.executor.lifecycle.wait_healthy(
                    self.startup_timeout_s
                )
                if not healthy:
                    await self._close_resources()
                    raise RuntimeError(
                        "initial backend did not become healthy: "
                        f"{start_detail}; {health_detail}; previous probe: {detail}"
                    )
                self.startup_detail = (
                    f"backend ownership established ({stop_detail}); "
                    f"default backend started; {health_detail}"
                )
                warmed, warmup_detail = await self.executor.lifecycle.warm_up(
                    self.controller.active_policy
                )
                if not warmed:
                    await self.executor.lifecycle.stop()
                    await self._close_resources()
                    raise RuntimeError(
                        "initial backend performance warm-up failed: " + warmup_detail
                    )
                self.startup_detail += f"; {warmup_detail}"
        else:
            self.startup_detail = "backend ownership disabled"
        if self.adaptive_enabled:
            self._control_task = asyncio.create_task(
                self._control_loop(), name="adaptive-control-loop"
            )
        self._audit("startup", {"detail": self.startup_detail})

    async def close(self, _app: web.Application) -> None:
        if self._control_task is not None:
            self._control_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._control_task
            self._control_task = None
        self._audit("shutdown", {"detail": "gateway cleanup"})
        await self._close_resources()

    async def handle_completions(self, request: web.Request) -> web.StreamResponse:
        started_at_s = time.monotonic()
        request_id = self._next_request_id
        self._next_request_id += 1
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.json_response({"error": "request body must be JSON"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response({"error": "request body must be an object"}, status=400)
        if payload.get("stream") is not True:
            return web.json_response(
                {"error": "the measured gateway currently requires stream=true"},
                status=400,
            )
        try:
            input_tokens, output_tokens = self.token_counter.request_shape(payload)
            shape = self.controller.observe_request(
                RequestObservation(started_at_s, input_tokens, output_tokens)
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        try:
            await self.admission_gate.acquire(started_at_s)
        except AdmissionRejected as exc:
            completed_at_s = time.monotonic()
            self._append_event(
                RequestEvent(
                    request_id,
                    started_at_s,
                    completed_at_s,
                    input_tokens,
                    output_tokens,
                    shape,
                    False,
                    exc.status,
                    False,
                    None,
                    (completed_at_s - started_at_s) * 1000,
                    exc.reason,
                )
            )
            return web.json_response(
                {"error": exc.reason},
                status=exc.status,
                headers={"Retry-After": f"{max(1, round(exc.retry_after_s))}"},
            )

        backend_payload = dict(payload)
        backend_payload["stream"] = True
        backend_payload["return_token_ids"] = True
        first_token_at_s: float | None = None
        status_code = 502
        error: str | None = None
        downstream: web.StreamResponse | None = None
        success = False
        try:
            assert self._session is not None
            endpoint = f"{self.backend_base_url}/v1/completions"
            request_timeout = aiohttp.ClientTimeout(total=self.backend_request_timeout_s)
            async with self._session.post(
                endpoint,
                json=backend_payload,
                timeout=request_timeout,
            ) as backend_response:
                status_code = backend_response.status
                if status_code != 200:
                    body = await backend_response.read()
                    error = f"backend returned HTTP {status_code}"
                    return web.Response(
                        body=body,
                        status=status_code,
                        content_type=backend_response.content_type,
                    )

                downstream = web.StreamResponse(
                    status=200,
                    headers={
                        "Content-Type": backend_response.headers.get(
                            "Content-Type", "text/event-stream"
                        ),
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                    },
                )
                await downstream.prepare(request)
                tracker = CompletionSseTracker()
                async for chunk in backend_response.content.iter_any():
                    if tracker.feed(chunk) and first_token_at_s is None:
                        first_token_at_s = time.monotonic()
                    await downstream.write(chunk)
                if tracker.finish() and first_token_at_s is None:
                    first_token_at_s = time.monotonic()
                success = tracker.seen_token
                if not success:
                    error = "backend stream ended without a generated token"
                with suppress(ConnectionError, RuntimeError):
                    await downstream.write_eof()
                return downstream
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            if downstream is None:
                return web.json_response({"error": error}, status=502)
            with suppress(ConnectionError, RuntimeError):
                await downstream.write_eof()
            return downstream
        finally:
            completed_at_s = time.monotonic()
            ttft_ms = (
                None
                if first_token_at_s is None
                else (first_token_at_s - started_at_s) * 1000
            )
            e2el_ms = (completed_at_s - started_at_s) * 1000
            self.slo_collector.record(
                CompletedRequest(
                    completed_at_s,
                    shape,
                    ttft_ms,
                    e2el_ms,
                    success,
                    request_id,
                )
            )
            self._append_event(
                RequestEvent(
                    request_id,
                    started_at_s,
                    completed_at_s,
                    input_tokens,
                    output_tokens,
                    shape,
                    True,
                    status_code,
                    success,
                    ttft_ms,
                    e2el_ms,
                    error,
                )
            )
            await self.admission_gate.release()

    async def handle_health(self, _request: web.Request) -> web.Response:
        backend_healthy = await self._backend_healthy()
        ready = backend_healthy and not self.admission_gate.paused
        payload = {
            "status": "ready" if ready else "not_ready",
            "backend_healthy": backend_healthy,
            "admission": self.admission_gate.snapshot(),
            "active_policy": self.controller.active_policy_name,
            "execution_in_progress": self.execution_in_progress,
        }
        return web.json_response(payload, status=200 if ready else 503)

    async def handle_state(self, _request: web.Request) -> web.Response:
        now_s = time.monotonic()
        return web.json_response(
            {
                "controller": self.controller.state_dict(),
                "adaptive_enabled": self.adaptive_enabled,
                "admission": self.admission_gate.snapshot(),
                "backend_healthy": await self._backend_healthy(),
                "execution_in_progress": self.execution_in_progress,
                "startup_detail": self.startup_detail,
                "control_error": self.control_error,
                "rolling_slo_samples": self.slo_collector.sample_count(now_s),
                "recent_decisions": list(self.decisions),
                "recent_executions": list(self.executions),
            }
        )

    async def handle_events(self, request: web.Request) -> web.Response:
        try:
            limit = min(200, max(1, int(request.query.get("limit", "50"))))
        except ValueError:
            return web.json_response({"error": "limit must be an integer"}, status=400)
        return web.json_response(
            {"events": [asdict(event) for event in list(self.events)[-limit:]]}
        )

    async def run_control_once(self, now_s: float | None = None) -> None:
        if not self.adaptive_enabled:
            return
        now_s = time.monotonic() if now_s is None else now_s
        decision = self.controller.tick(now_s)
        self._record_decision(decision.to_dict())
        if decision.action in {"switch", "rollback"}:
            await self._execute(decision)
            return

        metrics = self.slo_collector.metrics_for(self.controller.active_policy, now_s)
        slo_decision = self.controller.report_slo_window(now_s, metrics)
        self._record_decision(slo_decision.to_dict())
        if slo_decision.action in {"switch", "rollback"}:
            await self._execute(slo_decision)

    async def _execute(self, decision: Any) -> ExecutionResult:
        self.execution_in_progress = True
        started_at_s = time.monotonic()
        self._audit("execution_started", {
            "started_at_s": started_at_s,
            "from_policy": decision.from_policy,
            "target_policy": decision.to_policy,
            "action": decision.action,
        })
        try:
            result = await self.executor.execute(decision)
            completed_at_s = time.monotonic()
            self._record_execution({
                **result.to_dict(),
                "started_at_s": started_at_s,
                "completed_at_s": completed_at_s,
                "duration_s": completed_at_s - started_at_s,
                "requires_server_restart": decision.requires_server_restart,
            })
            self.slo_collector.clear()
            return result
        finally:
            self.execution_in_progress = False

    async def _control_loop(self) -> None:
        interval_s = self.controller.config.minimum_evaluation_interval_seconds
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self.run_control_once()
                self.control_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.control_error = f"{type(exc).__name__}: {exc}"

    async def _backend_healthy(self) -> bool:
        if self._session is None:
            return False
        try:
            timeout = aiohttp.ClientTimeout(total=2)
            async with self._session.get(
                f"{self.backend_base_url}/health", timeout=timeout
            ) as response:
                return response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    def _append_event(self, event: RequestEvent) -> None:
        self.events.append(event)
        self._audit("request", asdict(event))

    def _record_decision(self, decision: dict[str, Any]) -> None:
        self.decisions.append(decision)
        self._audit("decision", decision)

    def _record_execution(self, execution: dict[str, Any]) -> None:
        self.executions.append(execution)
        self._audit("execution", execution)

    def _audit(self, kind: str, payload: Mapping[str, Any]) -> None:
        if self._audit_file is None:
            return
        record = {
            "recorded_at_unix_s": time.time(),
            "kind": kind,
            "payload": dict(payload),
        }
        self._audit_file.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def _close_resources(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        if self._audit_file is not None:
            self._audit_file.close()
            self._audit_file = None


def create_gateway_app(runtime: GatewayRuntime) -> web.Application:
    return runtime.create_app()
