"""Dry-run by default. Four static development runs reuse audited stage-8 traces."""
import argparse
import asyncio
import hashlib
import json
import math
from pathlib import Path
import signal
from types import SimpleNamespace

from audit_alignment_pairs import audit_batch


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan(reference):
    # Read-only independent audit must pass before reusing reference inputs.
    audit_batch(reference)
    manifest = json.loads((reference/'batch_manifest.json').read_text())
    cfg = manifest['config']
    if [p['seed'] for p in cfg['pairs']] != [202, 203]:
        raise ValueError('this development protocol requires seeds 202 and 203')
    duration = sum(p['seconds'] for p in cfg['phases'])
    if not math.isfinite(duration) or not 0 < duration <= 180:
        raise ValueError('invalid bounded duration')
    cases = []
    for seed, rates in ((202, (3, 6)), (203, (6, 3))):
        folder = reference/f'seed{seed}'
        arrivals = json.loads((folder/'trace.json').read_text())
        expected = json.loads((folder/'trace_hash.json').read_text())['sha256']
        actual = hashlib.sha256(json.dumps(arrivals, sort_keys=True).encode()).hexdigest()
        if actual != expected:
            raise ValueError('reference trace changed')
        if not 0 < len(arrivals) <= 10000:
            raise ValueError('invalid request count')
        times = [r['at'] for r in arrivals]
        if times != sorted(times) or any(not math.isfinite(t) or not 0 <= t < duration for t in times):
            raise ValueError('invalid arrival times')
        for rate in rates:
            cases.append(dict(seed=seed, fixed_rate=rate, duration=duration,
                              requests=len(arrivals), trace_sha256=actual))
    return dict(protocol='static-endpoints-dev202-203-v1', cases=cases,
                reference_manifest_sha256=digest(reference/'batch_manifest.json'),
                config=cfg, profile=manifest['profile'],
                profile_sha256=manifest['profile_sha256'],
                caveat='static endpoints, not best-static oracle; cross-batch adaptive comparison is exploratory')


async def execute(args, planned):
    # Heavy/runtime imports happen only after explicit --execute.
    import aiohttp
    from owned_backend import OwnedBackend, save
    from run_alignment_pairs import warmup
    from run_pilot import one_mode
    from audit_alignment_pairs import audit_mode

    profile_path = args.source/planned['config']['slo_source']
    if digest(profile_path) != planned['profile_sha256']:
        raise ValueError('frozen SLO source changed')
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/'manifest.json', dict(**planned,
         source_files={p.name: digest(p) for p in Path(__file__).parent.glob('*.py')},
         frozen_dependencies={name: digest(args.source/'src/slo_autotuner'/name)
                              for name in ('executor.py', 'gateway.py', 'controller.py', 'mixed.py')}))
    report = dict(status='failed', completed=[])
    try:
        async with asyncio.timeout(1800):
            for case in planned['cases']:
                seed, rate = case['seed'], case['fixed_rate']
                arrivals = json.loads((args.reference/f'seed{seed}/trace.json').read_text())
                if hashlib.sha256(json.dumps(arrivals, sort_keys=True).encode()).hexdigest() != case['trace_sha256']:
                    raise ValueError('trace changed after planning')
                folder = args.output/f'seed{seed}-static{rate}'
                folder.mkdir()
                save(folder/'trace.json', arrivals)
                config = {**planned['config'], 'seed': seed, 'fixed_rate': rate}
                owned = SimpleNamespace(model=args.model, vllm=args.vllm, port=args.port,
                                        output=folder/'backend', served_model_name=config['model_name'])
                print(f'seed{seed} static{rate}: starting fresh backend', flush=True)
                async with asyncio.timeout(480):
                    async with OwnedBackend(owned) as backend:
                        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12),
                                                         connector=aiohttp.TCPConnector(limit=128)) as session:
                            save(owned.output/'warmup.json', await warmup(session, backend.url, config['model_name']))
                            result = await one_mode('fixed', config, planned['profile'], arrivals,
                                                    case['duration'], session, backend.url, folder)
                cleanup = json.loads((owned.output/'cleanup.json').read_text())
                if not result['valid_plumbing'] or not cleanup['stopped']:
                    raise RuntimeError('invalid accounting/cleanup; stop without retry')
                audited = audit_mode(folder/'fixed', arrivals, 'fixed')
                save(folder/'audit.json', audited)
                report['completed'].append(dict(case=case, summary=result, audit=audited))
            report['status'] = 'passed'
    except BaseException as exc:
        report['error'] = repr(exc)
        raise
    finally:
        save(args.output/'report.json', report)


async def entry(args, planned):
    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, task.cancel)
    await execute(args, planned)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--model', type=Path)
    parser.add_argument('--vllm', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--port', type=int, default=8025)
    args = parser.parse_args()
    if args.execute and any(getattr(args, k) is None for k in ('source', 'model', 'vllm', 'output')):
        parser.error('--execute requires --source, --model, --vllm and --output')
    if not 1024 <= args.port <= 65535:
        parser.error('port outside allowed range')
    planned = plan(args.reference)
    print(json.dumps(planned, indent=2), flush=True)
    if args.execute:
        asyncio.run(entry(args, planned))


if __name__ == '__main__':
    main()
