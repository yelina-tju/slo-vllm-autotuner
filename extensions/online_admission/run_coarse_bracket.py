"""Bounded sequential GPU calibration; preview by default, no automatic resume."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import signal
from types import SimpleNamespace
from coarse_plan import validate, make_trace, drive, next_step


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def execute(args, config, traces):
    import aiohttp
    from owned_backend import OwnedBackend, save
    from run_alignment_pairs import warmup
    from run_pilot import one_mode
    from run_pressure_calibration import collect_queue
    from pressure_analysis import analyze_case

    source = args.source/config['slo_source']
    profile = next(p for p in json.loads(source.read_text())['profiles'] if p['name'] == config['profile'])
    if (profile['input_tokens'], profile['output_tokens'], profile['ttft_slo_ms'], profile['e2el_slo_ms']) != (256, 64, 100, 400):
        raise ValueError('frozen profile changed')
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/'manifest.json', dict(config=config, profile=profile, config_sha256=digest(args.config),
         profile_sha256=digest(source), source_files={p.name: digest(p) for p in Path(__file__).parent.glob('*.py')},
         frozen_dependencies={name: digest(args.source/'src/slo_autotuner'/name)
                              for name in ('executor.py', 'gateway.py', 'controller.py', 'mixed.py')}))
    for seed, arrivals in traces.items():
        save(args.output/f'trace-{seed}.json', arrivals)
        save(args.output/f'trace-{seed}-hash.json', dict(sha256=hashlib.sha256(
            json.dumps(arrivals, sort_keys=True).encode()).hexdigest()))
    report = dict(status='failed', completed=[])

    async def run_case(seed, rate):
        folder = args.output/f'seed{seed}-static{rate}'
        folder.mkdir()
        cfg = {**config, 'seed': seed, 'fixed_rate': rate}
        owned = SimpleNamespace(model=args.model, vllm=args.vllm, port=args.port,
                                output=folder/'backend', served_model_name=config['model_name'])
        print(f'seed{seed} static{rate}: starting fresh backend', flush=True)
        async with asyncio.timeout(480):
            async with OwnedBackend(owned) as backend:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12),
                                                 connector=aiohttp.TCPConnector(limit=128)) as session:
                    save(owned.output/'warmup.json', await warmup(session, backend.url, config['model_name']))
                    stop = asyncio.Event()
                    sampler = asyncio.create_task(collect_queue(session, backend.url, folder/'queue.jsonl', stop))
                    print(f'seed{seed} static{rate}: traffic {len(traces[seed])} requests / 120s', flush=True)
                    try:
                        summary = await one_mode('fixed', cfg, profile, traces[seed], 120, session, backend.url, folder)
                    finally:
                        stop.set()
                        try:
                            await sampler
                        finally:
                            if not sampler.done():
                                sampler.cancel()
                                await asyncio.gather(sampler, return_exceptions=True)
        if not json.loads((owned.output/'cleanup.json').read_text())['stopped'] or not summary['valid_plumbing']:
            raise RuntimeError('invalid accounting/backend/cleanup; stop without retry')
        result = analyze_case(folder, traces[seed], seed, rate)
        save(folder/'analysis.json', result)
        print(f'seed{seed} static{rate}: {result["classification"]}; breached_windows={result["breached_windows"]}', flush=True)
        return result

    def checkpoint(completed):
        save(args.output/f'checkpoint-{len(completed):02d}.json',
             dict(completed=completed, next_step=next_step(completed)))

    try:
        async with asyncio.timeout(3000):
            report['selection'] = await drive(run_case, report['completed'], checkpoint)
        report['status'] = 'passed'
    except BaseException as exc:
        report['error'] = repr(exc)
        raise
    finally:
        save(args.output/'report.json', report)


async def entry(args, config, traces):
    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, task.cancel)
    await execute(args, config, traces)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('coarse_config.json'))
    parser.add_argument('--execute', action='store_true')
    for key in ('source', 'model', 'vllm', 'output'):
        parser.add_argument('--'+key, type=Path)
    parser.add_argument('--port', type=int, default=8029)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    validate(config)
    traces = {seed: make_trace(seed) for seed in (307, 308)}
    if args.execute and any(getattr(args, k) is None for k in ('source', 'model', 'vllm', 'output')):
        parser.error('execution requires source, model, vllm and output')
    if not 1024 <= args.port <= 65535:
        parser.error('port outside allowed range')
    print(json.dumps(dict(config=config, counts={s: len(t) for s, t in traces.items()},
                          first_step=next_step([])), indent=2), flush=True)
    if args.execute:
        asyncio.run(entry(args, config, traces))
