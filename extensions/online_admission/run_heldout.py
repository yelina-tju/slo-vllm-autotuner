"""Six bounded recovery cases; preview only by default. No resume or retries."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import signal
from types import SimpleNamespace
from heldout_protocol import CONFIG, case_config, prepare, arguments, validate_runtime
from heldout_plan import plan
from recovery_analysis import analyze_case
from heldout_analysis import verdict


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def execute(args, traces, frozen):
    import aiohttp
    from owned_backend import OwnedBackend, save
    from run_alignment_pairs import warmup
    from run_pilot import one_mode
    from run_pressure_calibration import collect_queue
    from audit_alignment_pairs import require
    prior = json.loads((args.calibration/'report.json').read_text())
    require(prior['status'] == 'passed' and prior['selection']['status'] == 'candidate_found'
            and (prior['selection']['low_rate'], prior['selection']['high_rate']) == (24, 48), 'missing calibration')
    source = args.source/CONFIG['slo_source']
    profile = next(p for p in json.loads(source.read_text())['profiles'] if p['name'] == CONFIG['profile'])
    require((profile['input_tokens'], profile['output_tokens'], profile['ttft_slo_ms'], profile['e2el_slo_ms'])
            == (256, 64, 100, 400), 'SLO/shape changed')
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/'manifest.json', dict(config=CONFIG, profile=profile, profile_sha256=sha(source),
         calibration_report_sha256=sha(args.calibration/'report.json'),
         source_files={p.name: sha(p) for p in Path(__file__).parent.glob('*.py')},
         frozen_protocol=frozen,
         frozen_dependencies={name: sha(args.source/'src/slo_autotuner'/name)
                              for name in ('executor.py', 'gateway.py', 'controller.py', 'mixed.py')}))
    save(args.output/'frozen-protocol.json', frozen)
    for seed, arrivals in traces.items():
        save(args.output/f'trace-{seed}.json', arrivals)
        save(args.output/f'trace-{seed}-hash.json', dict(sha256=hashlib.sha256(json.dumps(arrivals, sort_keys=True).encode()).hexdigest()))
    report = dict(status='failed', completed=[])
    try:
        async with asyncio.timeout(3900):
            for item in plan():
                seed, arm = item['seed'], item['arm']
                cfg, mode = case_config(CONFIG, seed, arm)
                folder = args.output/f'seed{seed}-{arm}'
                folder.mkdir()
                owned = SimpleNamespace(model=args.model, vllm=args.vllm, port=args.port,
                                        output=folder/'backend', served_model_name=CONFIG['model_name'])
                print(f'seed{seed} {arm}: starting fresh backend', flush=True)
                async with asyncio.timeout(600):
                    async with OwnedBackend(owned) as backend:
                        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12),
                                                         connector=aiohttp.TCPConnector(limit=128)) as session:
                            save(owned.output/'warmup.json', await warmup(session, backend.url, CONFIG['model_name']))
                            stop = asyncio.Event()
                            sampler = asyncio.create_task(collect_queue(session, backend.url, folder/'queue.jsonl', stop))
                            print(f'seed{seed} {arm}: traffic {len(traces[seed])} / 240s', flush=True)
                            try:
                                summary = await one_mode(mode, cfg, profile, traces[seed], 240, session, backend.url, folder)
                            finally:
                                stop.set()
                                try:
                                    await sampler
                                finally:
                                    if not sampler.done():
                                        sampler.cancel()
                                        await asyncio.gather(sampler, return_exceptions=True)
                require(json.loads((owned.output/'cleanup.json').read_text())['stopped'] and summary['valid_plumbing'],
                        'invalid accounting/backend/cleanup; no retry')
                result = analyze_case(folder, traces[seed], seed, arm)
                save(folder/'analysis.json', result)
                report['completed'].append(result)
                save(args.output/f'checkpoint-{len(report["completed"]):02d}.json', dict(completed=report['completed']))
                print(f'seed{seed} {arm}: audited goodput={result["goodput"]:.4f}; recovery={result["recovery"]}', flush=True)
            report['verdict'] = verdict(report['completed'])
            report['status'] = 'passed'
    except BaseException as exc:
        report['error'] = repr(exc)
        raise
    finally:
        save(args.output/'report.json', report)


async def entry(args, traces, frozen):
    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, task.cancel)
    await execute(args, traces, frozen)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    arguments(parser)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--freeze', type=Path, required=True)
    for key in ('source', 'model', 'vllm', 'output'):
        parser.add_argument('--'+key, type=Path)
    parser.add_argument('--port', type=int, default=8031)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('invalid port')
    frozen, traces = prepare(args, Path(__file__).parent)
    if args.execute:
        if any(getattr(args, k) is None for k in ('source', 'model', 'vllm', 'output')):
            parser.error('execution requires all paths')
        from audit_alignment_pairs import require
        require(json.loads(args.freeze.read_text()) == frozen, 'prelaunch freeze changed')
        validate_runtime(args, frozen)
        asyncio.run(entry(args, traces, frozen))
    else:
        with args.freeze.open('x') as stream:
            json.dump(frozen, stream, indent=2)
        print(json.dumps(dict(status='frozen_no_gpu_started', cases=plan(),
                              counts={s: len(t) for s, t in traces.items()}), indent=2))

