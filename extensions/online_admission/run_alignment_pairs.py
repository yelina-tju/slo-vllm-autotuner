"""Four bounded sequential runs, fresh backend per mode; no automatic retries."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import signal
from types import SimpleNamespace
import aiohttp
from owned_backend import OwnedBackend, save
from run_pilot import one_mode, trace, digest
from feedback import Config
from slo_autotuner.gateway import CompletionSseTracker


def validate(config):
    Config(**config['feedback'])
    if len(config['pairs']) != 2 or len({p['seed'] for p in config['pairs']}) != 2:
        raise ValueError('exactly two distinct development seeds required')
    if any(sorted(p['order']) != ['adaptive_deadline', 'adaptive_fixed'] for p in config['pairs']):
        raise ValueError('each pair needs both adaptive modes exactly once')
    if config['pairs'][0]['order'] != list(reversed(config['pairs'][1]['order'])):
        raise ValueError('order must be reversed for the second pair')
    if sum(p['seconds'] for p in config['phases']) > 180:
        raise ValueError('development duration exceeds bound')
    for pair in config['pairs']:
        arrivals, _ = trace({**config, 'seed': pair['seed']})
        if len(arrivals) > 10000:
            raise ValueError('too many requests')


async def warmup(session, url, model):
    records = []
    for _ in range(4):
        tracker = CompletionSseTracker()
        async with session.post(url+'/v1/completions', json=dict(model=model, prompt=list(range(100, 356)),
                                max_tokens=64, ignore_eos=True, stream=True, temperature=0)) as response:
            if response.status != 200:
                raise RuntimeError('warmup HTTP failure')
            async for chunk in response.content.iter_any():
                tracker.feed(chunk)
            tracker.finish()
            if not (tracker.seen_token and tracker.seen_done):
                raise RuntimeError('warmup incomplete')
            records.append(dict(token=True, done=True, status=200))
    return records


async def run(args):
    config = json.loads(args.config.read_text())
    validate(config)
    source = args.source/config['slo_source']
    profile = next(p for p in json.loads(source.read_text())['profiles'] if p['name'] == config['profile'])
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/'batch_manifest.json', dict(config=config, profile=profile, profile_sha256=digest(source),
         config_sha256=digest(args.config), source_files={p.name: digest(p) for p in Path(__file__).parent.glob('*.py')},
         frozen_dependencies={name: digest(args.source/'src/slo_autotuner'/name)
                              for name in ('executor.py', 'gateway.py', 'controller.py', 'mixed.py')}))
    report = dict(status='failed', completed=[])
    try:
        async with asyncio.timeout(1800):
            for pair in config['pairs']:
                seed = pair['seed']
                per_config = {**config, 'seed': seed}
                arrivals, duration = trace(per_config)
                pair_dir = args.output/f'seed{seed}'
                pair_dir.mkdir()
                save(pair_dir/'trace.json', arrivals)
                save(pair_dir/'trace_hash.json', dict(sha256=hashlib.sha256(json.dumps(arrivals, sort_keys=True).encode()).hexdigest()))
                for mode in pair['order']:
                    owned_args = SimpleNamespace(model=args.model, vllm=args.vllm, port=args.port,
                                                 output=pair_dir/f'{mode}-backend', served_model_name=config['model_name'])
                    print(f'seed{seed} {mode}: starting fresh backend', flush=True)
                    async with asyncio.timeout(480):
                        async with OwnedBackend(owned_args) as backend:
                            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12),
                                                             connector=aiohttp.TCPConnector(limit=128)) as session:
                                warm = await warmup(session, backend.url, config['model_name'])
                                save(owned_args.output/'warmup.json', warm)
                                print(f'seed{seed} {mode}: warmed; {len(arrivals)} requests/{duration}s', flush=True)
                                summary = await one_mode(mode, per_config, profile, arrivals, duration,
                                                         session, backend.url, pair_dir)
                    cleanup = json.loads((owned_args.output/'cleanup.json').read_text())
                    if not cleanup['stopped'] or not summary['valid_plumbing']:
                        raise RuntimeError('invalid accounting or cleanup; stop remaining runs for review')
                    report['completed'].append(dict(seed=seed, mode=mode, summary=summary))
                    save(pair_dir/f'{mode}-complete.json', dict(summary=summary, cleanup=cleanup))
            report['status'] = 'passed'
    except BaseException as exc:
        report['error'] = repr(exc)
        raise
    finally:
        save(args.output/'batch_report.json', report)


async def entry(args):
    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, task.cancel)
    await run(args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('alignment_pairs_config.json'))
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--vllm', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8023)
    asyncio.run(entry(parser.parse_args()))
