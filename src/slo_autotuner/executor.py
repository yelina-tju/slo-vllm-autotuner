"""Single-GPU policy executor with drain and startup-failure rollback."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
import time
from typing import Protocol

import aiohttp

from .controller import (
    AdaptiveServingController,
    ControlDecision,
    PolicyCatalog,
    ServingPolicy,
)


class AdmissionRejected(RuntimeError):
    def __init__(self, reason: str, status: int, retry_after_s: float) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.retry_after_s = retry_after_s


class AdmissionGate:
    """Pauseable token-bucket admission gate with in-flight draining."""

    def __init__(self, rate_limit_rps: float, burst_seconds: float = 0.25) -> None:
        if rate_limit_rps <= 0 or burst_seconds <= 0:
            raise ValueError("rate limit and burst_seconds must be positive")
        self._condition = asyncio.Condition()
        self._paused = False
        self._rate_limit_rps = rate_limit_rps
        self._burst_seconds = burst_seconds
        self._capacity = max(1.0, rate_limit_rps * burst_seconds)
        self._tokens = self._capacity
        self._last_refill_s = time.monotonic()
        self._in_flight = 0

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def rate_limit_rps(self) -> float:
        return self._rate_limit_rps

    async def acquire(self, now_s: float | None = None) -> None:
        now_s = time.monotonic() if now_s is None else now_s
        async with self._condition:
            if self._paused:
                raise AdmissionRejected("admission paused", 503, 1.0)
            self._refill(now_s)
            if self._tokens < 1.0:
                wait_s = (1.0 - self._tokens) / self._rate_limit_rps
                raise AdmissionRejected("admission rate exceeded", 429, wait_s)
            self._tokens -= 1.0
            self._in_flight += 1

    async def release(self) -> None:
        async with self._condition:
            if self._in_flight <= 0:
                raise RuntimeError("release called with no in-flight request")
            self._in_flight -= 1
            self._condition.notify_all()

    async def pause(self) -> None:
        async with self._condition:
            self._paused = True

    async def resume(self, rate_limit_rps: float) -> None:
        if rate_limit_rps <= 0:
            raise ValueError("rate_limit_rps must be positive")
        async with self._condition:
            self._rate_limit_rps = rate_limit_rps
            self._capacity = max(1.0, rate_limit_rps * self._burst_seconds)
            self._tokens = self._capacity
            self._last_refill_s = time.monotonic()
            self._paused = False
            self._condition.notify_all()

    async def wait_for_drain(self, timeout_s: float) -> bool:
        async def wait_until_empty() -> None:
            async with self._condition:
                while self._in_flight:
                    await self._condition.wait()

        try:
            await asyncio.wait_for(wait_until_empty(), timeout=timeout_s)
        except TimeoutError:
            return False
        return True

    def snapshot(self) -> dict[str, float | int | bool]:
        return {
            "paused": self._paused,
            "in_flight": self._in_flight,
            "rate_limit_rps": self._rate_limit_rps,
            "available_tokens": self._tokens,
        }

    def _refill(self, now_s: float) -> None:
        elapsed = max(0.0, now_s - self._last_refill_s)
        self._tokens = min(
            self._capacity, self._tokens + elapsed * self._rate_limit_rps
        )
        self._last_refill_s = now_s


class ServerLifecycle(Protocol):
    async def stop(self) -> tuple[bool, str]: ...

    async def start(self, policy: ServingPolicy) -> tuple[bool, str]: ...

    async def wait_healthy(self, timeout_s: float) -> tuple[bool, str]: ...

    async def warm_up(self, policy: ServingPolicy) -> tuple[bool, str]: ...


@dataclass(frozen=True)
class ExecutionResult:
    timestamp_s: float
    action: str
    status: str
    from_policy: str
    target_policy: str
    active_policy: str
    drained: bool
    admission_resumed: bool
    detail: str
    steps: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class PolicyExecutor:
    """Apply one decision while preserving the last running server on failure."""

    def __init__(
        self,
        controller: AdaptiveServingController,
        catalog: PolicyCatalog,
        admission_gate: AdmissionGate,
        lifecycle: ServerLifecycle,
        drain_timeout_s: float = 120.0,
        startup_timeout_s: float = 120.0,
    ) -> None:
        self.controller = controller
        self.catalog = catalog
        self.admission_gate = admission_gate
        self.lifecycle = lifecycle
        self.drain_timeout_s = drain_timeout_s
        self.startup_timeout_s = startup_timeout_s
        self._lock = asyncio.Lock()

    async def execute(self, decision: ControlDecision) -> ExecutionResult:
        if decision.action not in {"switch", "rollback"}:
            raise ValueError("executor accepts only switch or rollback decisions")
        async with self._lock:
            return await self._execute_locked(decision)

    async def _execute_locked(self, decision: ControlDecision) -> ExecutionResult:
        now_s = time.monotonic()
        source = self.catalog.policies[decision.from_policy]
        target = self.catalog.policies[decision.to_policy]
        steps: list[str] = []
        await self.admission_gate.pause()
        steps.append("admission_paused")
        drained = await self.admission_gate.wait_for_drain(self.drain_timeout_s)
        if not drained:
            self.controller.restore_after_execution_failure(
                decision,
                now_s,
                self.controller.config.rollback_cooldown_seconds,
            )
            await self.admission_gate.resume(source.admission_limit_rps)
            return ExecutionResult(
                now_s,
                decision.action,
                "drain_timeout",
                source.name,
                target.name,
                source.name,
                False,
                True,
                "in-flight requests did not drain; current server was preserved",
                tuple(steps + ["drain_timeout", "source_admission_resumed"]),
            )
        steps.append("in_flight_drained")

        if not decision.requires_server_restart:
            await self.admission_gate.resume(target.admission_limit_rps)
            return ExecutionResult(
                now_s,
                decision.action,
                "applied",
                source.name,
                target.name,
                target.name,
                True,
                True,
                "admission policy updated without a server restart",
                tuple(steps + ["target_admission_resumed"]),
            )

        stopped, stop_detail = await self._safe_stop()
        if not stopped:
            self.controller.restore_after_execution_failure(
                decision,
                now_s,
                self.controller.config.rollback_cooldown_seconds,
            )
            source_healthy, source_health_detail = await self._safe_health_check(
                min(5.0, self.startup_timeout_s)
            )
            if source_healthy:
                await self.admission_gate.resume(source.admission_limit_rps)
                steps.extend(["stop_failed", "source_health_passed", "source_admission_resumed"])
            else:
                steps.extend(["stop_failed", "source_health_failed", "admission_kept_paused"])
            return ExecutionResult(
                now_s,
                decision.action,
                "stop_failed_source_healthy" if source_healthy else "stop_failed_unhealthy",
                source.name,
                target.name,
                source.name,
                True,
                source_healthy,
                f"{stop_detail}; {source_health_detail}",
                tuple(steps),
            )
        steps.append("source_stopped")

        started, start_detail = await self._safe_start(target)
        if started:
            steps.append("target_start_command_succeeded")
        else:
            steps.append("target_start_command_failed")
        healthy = False
        health_detail = "start command failed"
        if started:
            healthy, health_detail = await self._safe_health_check(
                self.startup_timeout_s
            )
        warmed = False
        warmup_detail = "health check failed"
        if healthy:
            steps.append("target_health_passed")
            warmed, warmup_detail = await self._safe_warm_up(target)
            steps.append("target_warmup_passed" if warmed else "target_warmup_failed")
        if healthy and warmed:
            await self.admission_gate.resume(target.admission_limit_rps)
            return ExecutionResult(
                now_s,
                decision.action,
                "applied",
                source.name,
                target.name,
                target.name,
                True,
                True,
                f"{start_detail}; {health_detail}; {warmup_detail}",
                tuple(steps + ["target_admission_resumed"]),
            )

        if not healthy:
            steps.append("target_health_failed")
        cleanup_stopped, cleanup_detail = await self._safe_stop()
        if not cleanup_stopped:
            self.controller.restore_after_execution_failure(
                decision,
                now_s,
                self.controller.config.rollback_cooldown_seconds,
            )
            return ExecutionResult(
                now_s,
                decision.action,
                "failed_target_could_not_stop",
                source.name,
                target.name,
                source.name,
                True,
                False,
                (
                    f"target failed: {start_detail}; {health_detail}; {warmup_detail}; "
                    f"failed target cleanup failed: {cleanup_detail}"
                ),
                tuple(steps + ["failed_target_stop_failed", "admission_kept_paused"]),
            )
        steps.append("failed_target_stopped")
        rollback_started, rollback_start_detail = await self._safe_start(source)
        if rollback_started:
            steps.append("source_restart_command_succeeded")
        else:
            steps.append("source_restart_command_failed")
        rollback_healthy = False
        rollback_health_detail = "rollback start command failed"
        rollback_warmed = False
        rollback_warmup_detail = "rollback health check failed"
        if rollback_started:
            rollback_healthy, rollback_health_detail = (
                await self._safe_health_check(self.startup_timeout_s)
            )
        if rollback_healthy:
            steps.append("source_health_passed")
            rollback_warmed, rollback_warmup_detail = await self._safe_warm_up(source)
            steps.append(
                "source_warmup_passed" if rollback_warmed else "source_warmup_failed"
            )
        self.controller.restore_after_execution_failure(
            decision,
            now_s,
            self.controller.config.rollback_cooldown_seconds,
        )
        if rollback_healthy and rollback_warmed:
            await self.admission_gate.resume(source.admission_limit_rps)
            return ExecutionResult(
                now_s,
                decision.action,
                "startup_failed_rolled_back",
                source.name,
                target.name,
                source.name,
                True,
                True,
                (
                    f"target failed: {start_detail}; {health_detail}; {warmup_detail}; "
                    f"rollback recovered: {rollback_start_detail}; "
                    f"{rollback_health_detail}; {rollback_warmup_detail}"
                ),
                tuple(steps + ["source_admission_resumed"]),
            )

        return ExecutionResult(
            now_s,
            decision.action,
            "startup_and_rollback_failed",
            source.name,
            target.name,
            source.name,
            True,
            False,
            (
                f"target failed: {start_detail}; {health_detail}; {warmup_detail}; "
                "rollback failed: "
                f"{rollback_start_detail}; {rollback_health_detail}"
                f"; {rollback_warmup_detail}"
            ),
            tuple(
                steps
                + [
                    "source_readiness_failed"
                    if rollback_healthy
                    else "source_health_failed",
                    "admission_kept_paused",
                ]
            ),
        )

    async def _safe_stop(self) -> tuple[bool, str]:
        try:
            return await self.lifecycle.stop()
        except Exception as exc:
            return False, f"stop raised {type(exc).__name__}: {exc}"

    async def _safe_start(self, policy: ServingPolicy) -> tuple[bool, str]:
        try:
            return await self.lifecycle.start(policy)
        except Exception as exc:
            return False, f"start raised {type(exc).__name__}: {exc}"

    async def _safe_health_check(self, timeout_s: float) -> tuple[bool, str]:
        try:
            return await self.lifecycle.wait_healthy(timeout_s)
        except Exception as exc:
            return False, f"health check raised {type(exc).__name__}: {exc}"

    async def _safe_warm_up(self, policy: ServingPolicy) -> tuple[bool, str]:
        try:
            return await self.lifecycle.warm_up(policy)
        except Exception as exc:
            return False, f"warm-up raised {type(exc).__name__}: {exc}"


class ShellServerLifecycle:
    """Operate the existing detached vLLM server through server_ctl.sh."""

    def __init__(
        self,
        project_root: Path,
        model_path: Path,
        vllm_bin: Path,
        health_url: str = "http://127.0.0.1:8000/health",
        poll_interval_s: float = 1.0,
        warmup_requests_per_shape: int = 4,
        served_model_name: str = "qwen2.5-1.5b",
    ) -> None:
        self.project_root = project_root
        self.model_path = model_path
        self.vllm_bin = vllm_bin
        self.health_url = health_url
        self.poll_interval_s = poll_interval_s
        self.warmup_requests_per_shape = warmup_requests_per_shape
        if warmup_requests_per_shape < 0:
            raise ValueError("warmup_requests_per_shape cannot be negative")
        self.served_model_name = served_model_name
        self._last_log_file = self.project_root / "logs" / "server.log"

    async def stop(self) -> tuple[bool, str]:
        return await self._run_ctl("stop")

    async def start(self, policy: ServingPolicy) -> tuple[bool, str]:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", policy.name)
        self._last_log_file = (
            self.project_root / "logs" / f"server_{safe_name}.log"
        )
        environment = {
            **os.environ,
            "MODEL_PATH": str(self.model_path),
            "SERVED_MODEL_NAME": self.served_model_name,
            "VLLM_BIN": str(self.vllm_bin),
            "ENABLE_PREFIX_CACHING": "false",
            "ENABLE_CHUNKED_PREFILL": "true",
            "LOG_FILE": str(self._last_log_file),
            **policy.server_environment(),
        }
        return await self._run_ctl("start", environment)

    async def wait_healthy(self, timeout_s: float) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout_s
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while time.monotonic() < deadline:
                try:
                    async with session.get(self.health_url) as response:
                        if response.status == 200:
                            return True, "health check passed"
                except (aiohttp.ClientError, TimeoutError):
                    pass
                await asyncio.sleep(self.poll_interval_s)
        log_tail = await asyncio.to_thread(self._read_log_tail)
        detail = f"health check timed out after {timeout_s:g}s"
        if log_tail:
            detail += f"; log tail: {log_tail}"
        return False, detail

    async def warm_up(self, policy: ServingPolicy) -> tuple[bool, str]:
        if self.warmup_requests_per_shape == 0:
            return True, "performance warm-up disabled"
        shapes = {
            "balanced": ((256, 64),),
            "prefill_heavy_4x": ((1024, 64),),
            "decode_heavy_4x": ((256, 256),),
            "mixed_80_20": ((256, 64), (2048, 64)),
        }.get(policy.profile, ((256, 64),))
        endpoint = self.health_url.removesuffix("/health") + "/v1/completions"
        started = time.monotonic()
        timeout = aiohttp.ClientTimeout(total=60)
        completed = 0
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for shape_index, (input_tokens, output_tokens) in enumerate(shapes):
                for repetition in range(self.warmup_requests_per_shape):
                    base = 1000 + shape_index * 10000 + repetition * input_tokens
                    prompt = [1000 + ((base + index * 7919) % 100000) for index in range(input_tokens)]
                    payload = {
                        "model": self.served_model_name,
                        "prompt": prompt,
                        "max_tokens": output_tokens,
                        "temperature": 0.0,
                        "ignore_eos": True,
                        "stream": False,
                    }
                    try:
                        async with session.post(endpoint, json=payload) as response:
                            await response.read()
                            if response.status != 200:
                                return False, (
                                    f"performance warm-up HTTP {response.status} "
                                    f"after {completed} requests"
                                )
                    except (aiohttp.ClientError, TimeoutError) as exc:
                        return False, (
                            f"performance warm-up failed after {completed} requests: "
                            f"{type(exc).__name__}: {exc}"
                        )
                    completed += 1
        return True, (
            f"performance warm-up passed: {completed} requests in "
            f"{time.monotonic() - started:.2f}s"
        )

    def _read_log_tail(self, lines: int = 12) -> str:
        try:
            content = self._last_log_file.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return ""
        return " | ".join(content.splitlines()[-lines:])

    async def _run_ctl(
        self,
        action: str,
        environment: dict[str, str] | None = None,
    ) -> tuple[bool, str]:
        process = await asyncio.create_subprocess_exec(
            "bash",
            str(self.project_root / "scripts" / "server_ctl.sh"),
            action,
            cwd=self.project_root,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        detail = output.decode("utf-8", errors="replace").strip()
        return process.returncode == 0, detail
