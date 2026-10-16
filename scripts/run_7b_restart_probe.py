"""Independent 7B GPU executor probes; run only with exclusive GPU ownership.

--fail-target launches the target once with a nonexistent model path, then
restores the valid path for source recovery. Existing experiment files untouched.
"""
import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from run_gateway import build_runtime, parse_args
from slo_autotuner.controller import ControlDecision
from slo_autotuner.gateway import CompletionSseTracker
from runtime_paths import gpu_paths

ROOT = Path(__file__).resolve().parents[1]


async def run(fail, attempt):
    MODEL, vllm_bin = gpu_paths()
    if attempt and (not attempt.isascii() or not all(c.isalnum() or c in '-_' for c in attempt)):
        raise ValueError('attempt must contain only ASCII letters, digits, dash or underscore')
    label = 'restart_fail' if fail else 'restart_ok'
    if attempt:
        label = f'{label}_{attempt}'
    folder = ROOT / 'results' / f'fault7b_{label}'
    folder.mkdir()  # Preserve incomplete evidence; do not silently rerun.
    os.environ['RUN_DIR'] = str(ROOT / 'run' / f'fault7b_{label}')
    options = parse_args([
        '--project-root', str(ROOT), '--model-path', str(MODEL), '--tokenizer-path', str(MODEL),
        '--vllm-bin', str(vllm_bin),
        '--served-model-name', 'qwen2.5-7b', '--no-adaptive',
        '--controller-config', str(ROOT / 'configs/generalization_7b_controller.json'),
        '--workload-policy', str(ROOT / 'results/generalization_7b_workload_policy.json'),
        '--workload-profiles', str(ROOT / 'configs/generalization_7b_workload_profiles.json'),
        '--mixed-policy', str(ROOT / 'results/generalization_7b_mixed_capacity_final_policy.json'),
        '--initial-policy', 'balanced:mbt1024-seq256',
        '--audit-path', str(folder / 'gateway_audit.jsonl'),
    ])
    runtime = build_runtime(options)
    lifecycle = runtime.executor.lifecycle
    real_start = lifecycle.start
    injected = False
    async def start(policy):
        nonlocal injected
        original = lifecycle.model_path
        if fail and policy.max_num_batched_tokens == 2048 and not injected:
            injected = True
            lifecycle.model_path = folder / 'INTENTIONALLY_MISSING_MODEL'
        try:
            return await real_start(policy)
        finally:
            lifecycle.model_path = original
    lifecycle.start = start
    proxy = TestServer(runtime.create_app())
    report = {'status': 'failed', 'case': label, 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    pending = None
    transaction = None
    try:
        await proxy.start_server()
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session:
            payload = {'model': 'qwen2.5-7b', 'prompt': list(range(100, 356)),
                       'max_tokens': 64, 'ignore_eos': True, 'temperature': 0,
                       'stream': True, 'return_token_ids': True}
            first = asyncio.Event()
            async def completion():
                tracker = CompletionSseTracker()
                async with session.post(str(proxy.make_url('/v1/completions')), json=payload) as response:
                    if response.status != 200:
                        raise RuntimeError(f'completion status {response.status}')
                    async for chunk in response.content.iter_any():
                        if tracker.feed(chunk):
                            first.set()
                    tracker.finish()
                    if not tracker.seen_token or not tracker.seen_done:
                        raise RuntimeError('incomplete real inference stream')
                return time.monotonic()

            pending = asyncio.create_task(completion())
            await asyncio.wait_for(first.wait(), 30)
            report['in_flight_before'] = runtime.admission_gate.snapshot()
            if report['in_flight_before']['in_flight'] < 1:
                raise RuntimeError('in-flight trigger not reached')
            source = runtime.controller.active_policy
            target = runtime.controller.catalog.policies['balanced:mbt2048-seq256']
            now = time.monotonic()
            runtime.controller.force_active_policy(target.name, now, 0)
            decision = ControlDecision(now, 'switch', source.name, target.name, target.profile,
                'independent forced executor probe', None, 0, 0,
                target.admission_limit_rps, target.server_environment(), True)
            transaction = asyncio.create_task(runtime._execute(decision))
            deadline = time.monotonic() + 5
            while not runtime.admission_gate.paused:
                if time.monotonic() > deadline:
                    raise RuntimeError('pause was not observed')
                await asyncio.sleep(.001)
            async with session.post(str(proxy.make_url('/v1/completions')), json=payload) as response:
                report['paused_request_status'] = response.status
                await response.read()
            if report['paused_request_status'] != 503:
                raise RuntimeError('new request not rejected while paused')
            report['in_flight_completed_s'] = await pending
            result = await asyncio.wait_for(transaction, 480)
            report['execution'] = asdict(result)
            report['events'] = list(runtime.executions)
            report['target_failure_injected'] = injected
            expected_policy = source.name if fail else target.name
            if result.active_policy != expected_policy or not result.admission_resumed:
                raise RuntimeError('wrong final policy or admission not restored')
            if not fail and result.status != 'applied':
                raise RuntimeError('normal restart was not applied')
            if fail and (not injected or result.status == 'applied'):
                raise RuntimeError('expected target failure was not recorded')
            steps = result.steps
            if not steps.index('admission_paused') < steps.index('in_flight_drained') < steps.index('source_stopped'):
                raise RuntimeError('invalid pause/drain/stop ordering')
            healthy, detail = await lifecycle.wait_healthy(5)
            report['terminal_health'] = [healthy, detail]
            if not healthy:
                raise RuntimeError('terminal backend unhealthy')
            await completion()
            report['post_recovery_completion_passed'] = True
            report['status'] = 'passed'
    except Exception as exc:
        report['error'] = repr(exc)
        raise
    finally:
        for task in (pending, transaction):
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await proxy.close()
        stopped, detail = await lifecycle.stop()
        report['cleanup'] = [stopped, detail]
        if not stopped:
            report['status'] = 'failed'
        (folder / 'result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fail-target', action='store_true')
    parser.add_argument('--attempt', default='', help='explicit suffix for a preserved retry')
    args = parser.parse_args()
    asyncio.run(run(args.fail_target, args.attempt))
