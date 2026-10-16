#!/usr/bin/env python3
"""Run paired static/adaptive policy experiments against the real local GPU.

Each mode owns a fresh gateway/backend, but reuses exactly the same materialized
open-loop trace. Completed modes are resumable; incomplete files are preserved.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import time

import aiohttp
from aiohttp import web
from transformers import AutoTokenizer

from run_gateway import build_runtime, parse_args as gateway_args
from run_mixed_workload import build_token_population
from slo_autotuner.comparison import (
    build_trace,
    describe_model,
    fingerprint,
    score_records,
    score_windows,
)
from slo_autotuner.gateway import CompletionSseTracker
from slo_autotuner.mixed import load_request_classes


ROOT = Path(__file__).resolve().parents[1]

CONTROLLER_OVERRIDE_FIELDS = {
    "rolling_window_seconds",
    "minimum_samples",
    "minimum_evaluation_interval_seconds",
    "switch_confirmation_windows",
    "switch_margin",
    "compatible_recovery_confirmation_windows",
    "compatible_recovery_switch_margin",
    "compatible_recovery_rollback_enabled",
    "compatible_recovery_canary_admission_limits_rps",
    "compatible_recovery_canary_pass_windows",
    "max_profile_distance",
    "cooldown_seconds",
    "rollback_confirmation_windows",
    "rollback_cooldown_seconds",
    "minimum_slo_samples_per_class",
}


def save_new(path: Path, payload: object) -> None:
    # Exclusive creation protects previous evidence, including interrupted runs.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


async def issue(session, endpoint, spec, payload, started):
    scheduled = started + spec["scheduled_offset_s"]
    await asyncio.sleep(max(0, scheduled - time.monotonic()))
    dispatched = time.monotonic()
    first_token = None
    status, error = None, None
    tracker = CompletionSseTracker()
    try:
        async with session.post(endpoint, json=payload) as response:
            status = response.status
            if status != 200:
                raise RuntimeError(f"HTTP {status}: {(await response.text())[:300]}")
            async for chunk in response.content.iter_any():
                if tracker.feed(chunk) and first_token is None:
                    first_token = time.monotonic()
            if tracker.finish() and first_token is None:
                first_token = time.monotonic()
            if not tracker.seen_token or not tracker.seen_done:
                raise RuntimeError("incomplete SSE stream: missing token or [DONE]")
    except (aiohttp.ClientError, TimeoutError, RuntimeError, ConnectionError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    completed = time.monotonic()
    return {
        **spec,
        "dispatch_offset_s": dispatched - started,
        "completion_offset_s": completed - started,
        "client_launch_delay_ms": max(0, dispatched - scheduled) * 1000,
        "ttft_ms": None if first_token is None else (first_token - dispatched) * 1000,
        "e2el_ms": (completed - dispatched) * 1000,
        "status_code": status,
        "error": error,
    }


async def sample_gpu():
    process = await asyncio.create_subprocess_exec(
        "nvidia-smi", "--query-gpu=uuid,utilization.gpu,memory.used,power.draw",
        "--format=csv,noheader,nounits",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 5)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return {"error": "nvidia-smi timed out"}
    return {"csv": stdout.decode().strip(), "error": stderr.decode().strip() or None}


async def run_mode(args, mode, trace, phases, payloads, classes, run_key):
    mode_dir = args.output_dir / mode["name"]
    mode_dir.mkdir()  # Refuse to overwrite an incomplete mode silently.
    output = mode_dir / "result.json"
    controller_config = args.controller_config
    overrides = mode.get("controller_overrides", {})
    unknown_overrides = set(overrides) - CONTROLLER_OVERRIDE_FIELDS
    if unknown_overrides:
        raise ValueError(
            f"{mode['name']}: unsupported controller overrides: "
            f"{sorted(unknown_overrides)}"
        )
    if overrides:
        payload = json.loads(controller_config.read_text(encoding="utf-8"))
        payload.update(overrides)
        controller_config = mode_dir / "controller_config.json"
        save_new(controller_config, payload)
    options = [
        "--project-root", str(ROOT), "--model-path", str(args.model_path),
        "--tokenizer-path", str(args.model_path), "--vllm-bin", str(args.vllm_bin),
        "--served-model-name", args.served_model_name,
        "--initial-policy", mode["initial_policy"],
        "--adaptive" if mode["adaptive"] else "--no-adaptive",
        "--controller-config", str(controller_config),
        "--workload-policy", str(args.workload_policy),
        "--workload-profiles", str(args.workload_profiles),
        "--mixed-policy", str(args.mixed_policy),
        "--audit-path", str(mode_dir / "gateway_audit.jsonl"),
    ]
    runtime = build_runtime(gateway_args(options))
    runner = web.AppRunner(runtime.create_app())
    horizon = phases[-1]["end_s"]
    records, snapshots = [], []
    monitor = None
    oracle_task = None
    tasks = []
    try:
        print(f"{mode['name']}: starting {mode['initial_policy']}", flush=True)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 8080).start()
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60),
            connector=aiohttp.TCPConnector(limit=0),
        ) as session:
            # Identical direct-backend warm-up: no workload-detector contamination.
            warmups = []
            for class_name in (c.name for c in classes):
                index = next(i for i, spec in enumerate(trace) if spec["class_name"] == class_name)
                for _ in range(8):
                    warm = {**trace[index], "scheduled_offset_s": 0}
                    record = await issue(session, "http://127.0.0.1:8000/v1/completions",
                                         warm, payloads[index], time.monotonic())
                    warmups.append(record)
                    if record["error"]:
                        raise RuntimeError(f"warm-up failed: {record['error']}")
            save_new(mode_dir / "warmup.json", warmups)
            started = time.monotonic()
            started_unix = time.time()
            initial_state = runtime.controller.state_dict()
            print(f"{mode['name']}: trace started, {len(trace)} requests / {horizon:g}s", flush=True)

            async def run_oracle_transitions():
                for transition in mode.get("oracle_transitions", []):
                    boundary_s = float(transition["at_s"])
                    await asyncio.sleep(
                        max(0.0, started + boundary_s - time.monotonic())
                    )
                    decision = runtime.controller.force_profile_decision(
                        str(transition["profile"]),
                        time.monotonic(),
                        reason=(
                            f"oracle knows phase boundary at {boundary_s:g}s"
                        ),
                    )
                    runtime._record_decision(decision.to_dict())
                    await runtime._execute(decision)

            if mode.get("oracle_transitions"):
                if mode["adaptive"]:
                    raise ValueError("oracle transitions require adaptive=false")
                oracle_task = asyncio.create_task(run_oracle_transitions())

            async def observe():
                tick = 0
                with (mode_dir / "state_samples.jsonl").open("x", encoding="utf-8", buffering=1) as stream:
                    while True:
                        state = {
                            "offset_s": time.monotonic() - started,
                            "controller": runtime.controller.state_dict(),
                            "admission": runtime.admission_gate.snapshot(),
                            "execution_in_progress": runtime.execution_in_progress,
                            "control_error": runtime.control_error,
                            "gpu": await sample_gpu(),
                        }
                        snapshots.append(state)
                        stream.write(json.dumps(state) + "\n")
                        if tick % 6 == 0:
                            print(f"{mode['name']}: t={state['offset_s']:.0f}s completed={len(records)} "
                                  f"policy={runtime.controller.active_policy_name} "
                                  f"paused={runtime.admission_gate.paused}", flush=True)
                        tick += 1
                        await asyncio.sleep(5)

            monitor = asyncio.create_task(observe())
            with (mode_dir / "requests.jsonl").open("x", encoding="utf-8", buffering=1) as stream:
                async def measured(spec, payload):
                    record = await issue(session, "http://127.0.0.1:8080/v1/completions",
                                         spec, payload, started)
                    records.append(record)
                    stream.write(json.dumps(record) + "\n")

                tasks = [asyncio.create_task(measured(spec, payload))
                         for spec, payload in zip(trace, payloads)]
                await asyncio.gather(*tasks)
                await asyncio.sleep(max(0, started + horizon - time.monotonic()))
            if oracle_task is not None:
                await oracle_task
            # Finish a pending transaction, but do not trigger a new one after traffic ends.
            runtime.adaptive_enabled = False
            deadline = time.monotonic() + 400
            while runtime.execution_in_progress:
                if time.monotonic() > deadline:
                    raise RuntimeError("transaction still running 400s after measurement")
                await asyncio.sleep(1)
            records.sort(key=lambda r: r["request_id"])
            duration = max(horizon, max(r["completion_offset_s"] for r in records))
            executions = [
                {**item, "started_offset_s": item["started_at_s"] - started,
                 "completed_offset_s": item["completed_at_s"] - started}
                for item in runtime.executions
            ]
            summary = score_records(records, classes, duration)
            by_phase = {}
            for phase in phases:
                selected = [r for r in records if r["phase"] == phase["name"]]
                by_phase[phase["name"]] = score_records(selected, classes, phase["duration_s"])
            result = {
                "schema_version": 1, "status": "complete", "mode": mode,
                "run_key": run_key,
                "started_at_utc": datetime.fromtimestamp(started_unix, timezone.utc).isoformat(),
                "started_at_monotonic_s": started, "planned_horizon_s": horizon,
                "scored_duration_s": duration, "initial_state": initial_state,
                "final_state": runtime.controller.state_dict(),
                "final_admission": runtime.admission_gate.snapshot(),
                "control_errors": [s for s in snapshots if s["control_error"]],
                "summary": summary, "by_phase": by_phase,
                "executions": executions,
                "restart_count": sum(e["requires_server_restart"] for e in executions),
                "transition_duration_s": sum(e["duration_s"] for e in executions),
                "requests": records,
                **score_windows(records, classes, horizon, args.window_s),
            }
            # A completed measurement is valid only if the service is recoverable.
            healthy, detail = await runtime.executor.lifecycle.wait_healthy(5)
            if not healthy or runtime.admission_gate.paused or result["control_errors"]:
                save_new(mode_dir / "invalid_result.json", result)
                raise RuntimeError(f"invalid terminal service state: {detail}")
            save_new(output, result)
            print(f"{mode['name']}: DONE goodput={summary['request_goodput']:.3f} "
                  f"statuses={summary['status_counts']} transitions={len(executions)}", flush=True)
            return result
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        if oracle_task and not oracle_task.done():
            oracle_task.cancel()
            await asyncio.gather(oracle_task, return_exceptions=True)
        await runner.cleanup()
        stopped, detail = await runtime.executor.lifecycle.stop()
        print(f"{mode['name']}: backend cleanup stopped={stopped}: {detail}", flush=True)
        if not stopped:
            raise RuntimeError("backend cleanup failed; do not start another mode")


async def main(args):
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.seed is not None:
        config["seed"] = args.seed
    trace, phases = build_trace(config)
    classes = load_request_classes(args.mixed_workload_config)
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, local_files_only=True,
                                              trust_remote_code=False)
    population = build_token_population(tokenizer)
    payloads = []
    for spec in trace:
        payload = {
            "model": args.served_model_name, "stream": True, "return_token_ids": True,
            "ignore_eos": True, "temperature": 0.0, "max_tokens": spec["requested_output_tokens"],
            "prompt": random.Random(spec["prompt_seed"]).choices(population, k=spec["input_tokens"]),
        }
        spec["payload_sha256"] = fingerprint(payload)
        payloads.append(payload)
    source_paths = sorted((ROOT / "src" / "slo_autotuner").glob("*.py")) + [
        Path(__file__), ROOT / "scripts" / "run_gateway.py",
        ROOT / "scripts" / "serve.sh", ROOT / "scripts" / "server_ctl.sh",
        args.controller_config, args.workload_profiles, args.mixed_workload_config,
        args.workload_policy, args.mixed_policy,
    ]
    provenance = {str(p.resolve().relative_to(ROOT.resolve())): fingerprint(p.read_text(encoding="utf-8"))
                  for p in source_paths}
    manifest = {"config": config, "phases": phases, "trace": trace,
                "model": describe_model(args.model_path, args.served_model_name),
                "classes": [asdict(c) for c in classes], "source_fingerprints": provenance,
                "trace_sha256": fingerprint(trace)}
    run_key = fingerprint(manifest)
    manifest["run_key"] = run_key
    args.window_s = config["metric_window_seconds"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "trace_manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text())["run_key"] != run_key:
            raise RuntimeError("output directory belongs to a different trace/config/code; choose a new directory")
    else:
        save_new(manifest_path, manifest)
    summaries = []
    available_modes = {mode["name"] for mode in config["modes"]}
    unknown_modes = set(args.modes or ()) - available_modes
    if unknown_modes:
        raise ValueError(f"unknown modes for this config: {sorted(unknown_modes)}")
    for mode in config["modes"]:
        if args.modes and mode["name"] not in args.modes:
            continue
        result_path = args.output_dir / mode["name"] / "result.json"
        if result_path.exists():
            result = json.loads(result_path.read_text())
            if (result.get("run_key") != run_key or result.get("status") != "complete"
                    or len(result.get("requests", [])) != len(trace)):
                raise RuntimeError(f"invalid previous result: {result_path}")
            print(f"{mode['name']}: SKIP valid completed result", flush=True)
        else:
            result = await run_mode(args, mode, trace, phases, payloads, classes, run_key)
        summaries.append({key: result[key] for key in (
            "mode", "summary", "by_phase", "restart_count", "transition_duration_s",
            "tail_violation_area_s", "class_windows_without_success",
        )})
    print(json.dumps({"run_key": run_key, "modes": summaries}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "policy_comparison.json")
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--served-model-name", default="qwen2.5-1.5b")
    parser.add_argument("--vllm-bin", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--controller-config", type=Path,
                        default=ROOT / "configs" / "controller.json")
    parser.add_argument("--workload-policy", type=Path,
                        default=ROOT / "results" / "workload_policy.json")
    parser.add_argument("--workload-profiles", type=Path,
                        default=ROOT / "configs" / "workload_profiles.json")
    parser.add_argument("--mixed-policy", type=Path,
                        default=ROOT / "results" / "mixed_policy.json")
    parser.add_argument("--mixed-workload-config", type=Path,
                        default=ROOT / "configs" / "mixed_workload.json")
    parser.add_argument("--modes", nargs="+")
    asyncio.run(main(parser.parse_args()))
