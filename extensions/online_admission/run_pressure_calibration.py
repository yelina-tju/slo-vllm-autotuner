"""Six bounded static calibration runs. Preview only unless --execute is supplied."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import signal
import time
from types import SimpleNamespace

from pressure_analysis import validate, protocol_spec, make_trace, queue_metrics, analyze_case, select_pair


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def collect_queue(session, url, path, stop):
    import aiohttp
    count = 0
    with path.open('x', encoding='utf-8') as output:
        while not stop.is_set():
            row = dict(at=time.monotonic())
            try:
                async with session.get(url+'/metrics', timeout=aiohttp.ClientTimeout(total=2)) as response:
                    response.raise_for_status()
                    row['raw'] = await response.text()
                row['finished_at'] = time.monotonic()
                row['metrics'] = queue_metrics(row['raw'])
            except Exception as exc:
                row.update(finished_at=time.monotonic(), error=repr(exc))
                output.write(json.dumps(row)+'\n')
                output.flush()
                raise
            output.write(json.dumps(row)+'\n')
            output.flush()
            count += 1
            if count % 30 == 0:
                print(f'queue sample {count}: {row["metrics"]}', flush=True)
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass


async def execute(args, config):
    import aiohttp
    from owned_backend import OwnedBackend, save
    from run_alignment_pairs import warmup
    from run_pilot import one_mode

    seeds, rates, offered = protocol_spec(config)
    source = args.source/config['slo_source']
    profile = next(p for p in json.loads(source.read_text())['profiles'] if p['name'] == config['profile'])
    if (profile['input_tokens'], profile['output_tokens'], profile['ttft_slo_ms'], profile['e2el_slo_ms']) != (256, 64, 100, 400):
        raise ValueError('frozen balanced profile changed')
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/'manifest.json', dict(config=config, profile=profile, config_sha256=digest(args.config),
         profile_sha256=digest(source), source_files={p.name: digest(p) for p in Path(__file__).parent.glob('*.py')},
         frozen_dependencies={name: digest(args.source/'src/slo_autotuner'/name)
                              for name in ('executor.py', 'gateway.py', 'controller.py', 'mixed.py')}))
    report = dict(status='failed', completed=[])
    try:
        async with asyncio.timeout(3000):
            for order in config['orders']:
                seed = order['seed']
                arrivals = make_trace(seed, offered)
                save(args.output/f'trace-{seed}.json', arrivals)
                save(args.output/f'trace-{seed}-hash.json', dict(sha256=hashlib.sha256(
                    json.dumps(arrivals, sort_keys=True).encode()).hexdigest()))
                for rate in order['rates']:
                    folder = args.output/f'seed{seed}-static{rate}'
                    folder.mkdir()
                    run_cfg = {**config, 'seed': seed, 'fixed_rate': rate}
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
                                print(f'seed{seed} static{rate}: traffic {len(arrivals)} requests / 120s', flush=True)
                                try:
                                    summary = await one_mode('fixed', run_cfg, profile, arrivals, 120,
                                                             session, backend.url, folder)
                                finally:
                                    stop.set()
                                    try:
                                        await sampler
                                    finally:
                                        if not sampler.done():
                                            sampler.cancel()
                                            await asyncio.gather(sampler, return_exceptions=True)
                    cleanup = json.loads((owned.output/'cleanup.json').read_text())
                    if not cleanup['stopped'] or not summary['valid_plumbing']:
                        raise RuntimeError('invalid accounting/backend/cleanup; stop without retry')
                    result = analyze_case(folder, arrivals, seed, rate)
                    save(folder/'analysis.json', result)
                    report['completed'].append(result)
                    print(f'seed{seed} static{rate}: {result["classification"]}, breached_windows={result["breached_windows"]}', flush=True)
            report['selection'] = select_pair(report['completed'], seeds, rates)
            report['status'] = 'passed'
    except BaseException as exc:
        report['error'] = repr(exc)
        raise
    finally:
        save(args.output/'report.json', report)


async def entry(args, config):
    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, task.cancel)
    await execute(args, config)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('pressure_config.json'))
    parser.add_argument('--execute', action='store_true')
    for name in ('source', 'model', 'vllm', 'output'):
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--port', type=int, default=8027)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    validate(config)
    if args.execute and any(getattr(args, k) is None for k in ('source', 'model', 'vllm', 'output')):
        parser.error('execution requires source, model, vllm and output')
    if not 1024 <= args.port <= 65535:
        parser.error('port outside allowed range')
    seeds, rates, offered = protocol_spec(config)
    print(json.dumps(dict(config=config, counts={s: len(make_trace(s, offered)) for s in seeds}), indent=2), flush=True)
    if args.execute:
        asyncio.run(entry(args, config))
