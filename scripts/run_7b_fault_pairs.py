"""Independent real-GPU fault pairs; invoke only after final-evidence review.

Reuses the frozen benchmark harness without editing it. A loopback streaming
proxy delays the first upstream chunk for 60s after first applied capacity rise.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import compare_policies as benchmark
from runtime_paths import gpu_paths

ROOT = Path(__file__).resolve().parents[1]


class Injection:
    def __init__(self, enabled, delay):
        self.enabled, self.delay = enabled, delay
        self.armed = None
        self.records = []

    def applies(self, now):
        return self.enabled and self.armed is not None and self.armed <= now < self.armed + 60


async def run(seed, fault):
    model_path, vllm_bin = gpu_paths()
    directory = ROOT / 'results' / f'fault7b_{"delay" if fault else "healthy"}_seed{seed}'
    directory.mkdir(exist_ok=True)
    config = {
        'seed': seed, 'metric_window_seconds': 30,
        'phases': [
            {'name': 'mixed_shift', 'duration_s': 60, 'request_rate': 6, 'long_fraction': .2},
            {'name': 'balanced_return', 'duration_s': 270, 'request_rate': 8, 'long_fraction': 0},
        ],
        'modes': [
            {'name': name, 'adaptive': True,
             'initial_policy': 'mixed_80_20:selected:mbt1024_fcfs',
             'controller_overrides': {'compatible_recovery_canary_admission_limits_rps': stages}}
            for name, stages in [('binary_recovery', []), ('canary_recovery', [6, 9])]
        ],
    }
    if seed == 132:
        config['modes'].reverse()
    path = directory / 'config.json'
    rendered = json.dumps(config, indent=2)
    if path.exists() and path.read_text() != rendered:
        raise RuntimeError('existing protocol differs')
    path.write_text(rendered)
    workload = json.loads((ROOT / 'configs/generalization_7b_workload.json').read_text())
    short = next(c for c in workload['classes'] if c['name'] == 'interactive_short')
    delay = 1.25 * short['ttft_slo_ms'] / 1000
    states = {}
    current = None
    original_factory = benchmark.build_runtime

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session:
        async def health(request):
            async with session.get('http://127.0.0.1:8000/health') as response:
                return web.Response(status=response.status, body=await response.read())

        async def forward(request):
            payload = await request.json()
            state = current
            entered = time.monotonic()
            inject = state.applies(entered)
            record = {'payload_sha256': benchmark.fingerprint(payload),
                      'entered_s': entered, 'injected': inject, 'delay_s': delay if inject else 0}
            state.records.append(record)
            try:
                async with session.post('http://127.0.0.1:8000/v1/completions', json=payload) as upstream:
                    if upstream.status != 200:
                        return web.Response(status=upstream.status, body=await upstream.read())
                    downstream = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
                    await downstream.prepare(request)
                    first = True
                    async for chunk in upstream.content.iter_any():
                        if first:
                            record['upstream_first_chunk_s'] = time.monotonic()
                            if inject:
                                await asyncio.sleep(delay)
                            record['downstream_first_chunk_s'] = time.monotonic()
                            first = False
                        await downstream.write(chunk)
                    await downstream.write_eof()
                    return downstream
            except Exception as exc:
                record['error'] = repr(exc)
                raise
            finally:
                record['completed_s'] = time.monotonic()

        app = web.Application()
        app.router.add_get('/health', health)
        app.router.add_post('/v1/completions', forward)
        proxy = TestServer(app)
        await proxy.start_server()

        def factory(args):
            nonlocal current
            runtime = original_factory(args)
            mode = args.audit_path.parent.name
            current = Injection(fault, delay)
            state = current
            states[mode] = state
            runtime.backend_base_url = str(proxy.make_url('')).rstrip('/')
            original_execute = runtime._execute
            async def execute(decision):
                before = runtime.controller.catalog.policies[decision.from_policy].admission_limit_rps
                result = await original_execute(decision)
                if result.status == 'applied' and before == 3 and runtime.admission_gate.rate_limit_rps > 3 and state.armed is None:
                    state.armed = time.monotonic()
                return result
            runtime._execute = execute
            return runtime

        benchmark.build_runtime = factory
        args = SimpleNamespace(
            config=path, seed=None, modes=None, output_dir=directory,
            model_path=model_path,
            served_model_name='qwen2.5-7b',
            vllm_bin=vllm_bin,
            controller_config=ROOT / 'configs/generalization_7b_controller.json',
            workload_policy=ROOT / 'results/generalization_7b_workload_policy.json',
            workload_profiles=ROOT / 'configs/generalization_7b_workload_profiles.json',
            mixed_policy=ROOT / 'results/generalization_7b_mixed_capacity_final_policy.json',
            mixed_workload_config=ROOT / 'configs/generalization_7b_mixed.json',
        )
        try:
            await benchmark.main(args)
        finally:
            benchmark.build_runtime = original_factory
            for mode, state in states.items():
                output = directory / mode / 'fault_proxy.json'
                with output.open('x') as stream:
                    json.dump({'armed_s': state.armed, 'enabled': fault, 'delay_s': delay,
                               'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                               'records': state.records}, stream, indent=2)
            await proxy.close()
    print(f'FAULT_PAIR_COMPLETE seed={seed} fault={fault}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, choices=[130, 131, 132], required=True)
    parser.add_argument('--fault', action='store_true')
    args = parser.parse_args()
    if args.fault != (args.seed != 130):
        parser.error('130 is healthy; 131 and 132 require --fault')
    asyncio.run(run(args.seed, args.fault))
