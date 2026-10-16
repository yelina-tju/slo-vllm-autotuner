"""Bounded Linux-only GPU development smoke. Creates a NEW output directory.

Never finds/kills arbitrary servers: starts one private process group and cleans
only that group. Same backend stays warm for both modes; not a fair final trial.
"""
import argparse
import asyncio
from collections import Counter
from dataclasses import asdict, is_dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import random
import signal
import socket
import subprocess
import time
from types import SimpleNamespace

import aiohttp
from cohorts import ArrivalCohorts
from deadline_cohorts import DeadlineCohorts
from feedback import Config, Feedback
from hot_gate import HotAdmissionGate
from transport import StreamingPilot
from slo_autotuner.gateway import CompletionSseTracker


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, default=lambda v: asdict(v) if is_dataclass(v) else str(v))


def trace(config):
    rng = random.Random(config['seed'])
    result, offset = [], 0.0
    for phase in config['phases']:
        if not all(math.isfinite(phase[k]) and phase[k] > 0 for k in ('seconds', 'rps')):
            raise ValueError('invalid trace phase')
        t = rng.expovariate(phase['rps'])
        while t < phase['seconds']:
            result.append(dict(at=offset+t, prompt_seed=rng.randrange(2**31)))
            t += rng.expovariate(phase['rps'])
        offset += phase['seconds']
    return result, offset


def score(rows, duration, limits):
    ok = [r for r in rows if r['success']]
    compliant = [r for r in ok if r.get('ttft_ms') is not None
                 and r['ttft_ms'] <= limits[0] and r['e2el_ms'] <= limits[1]]
    scheduled = [r for r in compliant if r['ttft_ms']+1000*r['dispatch_lag_s'] <= limits[0]
                 and r['e2el_ms']+1000*r['dispatch_lag_s'] <= limits[1]]
    return dict(requests=len(rows), statuses=dict(Counter(str(r['status']) for r in rows)),
                successes=len(ok), service_slo_compliant=len(compliant),
                scheduled_slo_compliant=len(scheduled),
                service_goodput=len(compliant)/duration,
                scheduled_goodput=len(scheduled)/duration,
                max_dispatch_lag_s=max((r['dispatch_lag_s'] for r in rows), default=0))


async def one_mode(mode, config, profile, arrivals, duration, session, url, output):
    if mode not in ('fixed', 'adaptive', 'adaptive_fixed', 'adaptive_deadline'):
        raise ValueError('unknown mode')
    fixed_rate = config.get('fixed_rate', config['feedback'].get('initial', 3.0))
    if mode == 'fixed' and (type(fixed_rate) not in (int, float)
                            or not math.isfinite(fixed_rate) or fixed_rate <= 0):
        raise ValueError('fixed_rate must be a finite positive number')
    folder = output / mode
    folder.mkdir()
    limits = (profile['ttft_slo_ms'], profile['e2el_slo_ms'])
    feedback = Feedback([profile['name']], Config(**config['feedback']))
    gate = HotAdmissionGate(fixed_rate if mode == 'fixed' else feedback.rate)
    origin = time.monotonic()+.1
    alignment = config.get('cohort_alignment', 'fixed')
    if mode in ('adaptive_fixed', 'adaptive_deadline'):
        alignment = mode.removeprefix('adaptive_')
    if alignment not in ('fixed', 'deadline'):
        raise ValueError('unknown cohort alignment')
    if mode == 'fixed':
        alignment = 'fixed'
    cohort_type = DeadlineCohorts if alignment == 'deadline' and mode != 'fixed' else ArrivalCohorts
    cohorts = cohort_type({profile['name']: limits}, origin=origin,
                            width=config['cohort_seconds'], timeout=config['request_timeout_seconds'])
    pilot = StreamingPilot(SimpleNamespace(_lock=asyncio.Lock(), admission_gate=gate), feedback, cohorts)
    rows, tasks, transitions = [], set(), []
    task_errors = []
    stop_ticks = asyncio.Event()
    request_log = (folder/'requests.jsonl').open('x')
    control_log = (folder/'control.jsonl').open('x')
    write_json(folder/'run_metadata.json', dict(origin=origin, duration=duration, mode=mode,
                                                alignment=alignment, profile=profile, config=config,
                                                effective_initial_rate=gate.rate_limit_rps))

    async def send(i, arrival):
        intended = origin+arrival['at']
        lag = max(0, time.monotonic()-intended)
        rng = random.Random(arrival['prompt_seed'])
        payload = dict(model=config['model_name'], prompt=[rng.randrange(100, 20000) for _ in range(profile['input_tokens'])],
                       max_tokens=profile['output_tokens'], ignore_eos=True, temperature=0, return_token_ids=True)
        result = await pilot.request(session, url+'/v1/completions', payload, profile['name'])
        result.update(trace_id=i, scheduled_at_s=arrival['at'], dispatch_lag_s=lag)
        rows.append(result)
        request_log.write(json.dumps(result)+'\n')
        request_log.flush()

    async def ticks():
        await asyncio.sleep(max(0, origin-time.monotonic()))
        while not stop_ticks.is_set():
            if mode != 'fixed':
                records = await pilot.tick(actuation_deadline=origin+duration)
            else:
                records = [dict(window=w, audit=a, decision=None, applied=None)
                           for w, a in cohorts.advance(time.monotonic(), 0)]
            for record in records:
                record.update(rate=gate.rate_limit_rps, revision=feedback.revision,
                              observed_at_s=time.monotonic()-origin)
                control_log.write(json.dumps(record, default=asdict)+'\n')
                control_log.flush()
                if record['applied']:
                    transitions.append(record)
                    print(f'{mode}: applied rate={gate.rate_limit_rps:.3f} reason={record["decision"].reason}', flush=True)
            await asyncio.sleep(config['tick_seconds'])

    def finished(task):
        tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            task_errors.append(repr(task.exception()))

    ticker = asyncio.create_task(ticks())
    try:
        for i, arrival in enumerate(arrivals):
            await asyncio.sleep(max(0, origin+arrival['at']-time.monotonic()))
            if ticker.done():
                await ticker
                raise RuntimeError('ticker exited unexpectedly')
            if task_errors or len(tasks) >= config['max_pending_tasks']:
                raise RuntimeError(f'load driver failure: {task_errors}, pending={len(tasks)}')
            task = asyncio.create_task(send(i, arrival))
            tasks.add(task)
            task.add_done_callback(finished)
        await asyncio.sleep(max(0, origin+duration-time.monotonic()))
        if tasks:
            await asyncio.gather(*tasks)
        if task_errors:
            raise RuntimeError(str(task_errors))
        await asyncio.sleep(config['tick_seconds']*2)
        if ticker.done():
            await ticker
            raise RuntimeError('ticker exited before finalization')
        summary = score(rows, duration, limits)
        summary.update(mode=mode, duration=duration, transitions=len(transitions), final_rate=gate.rate_limit_rps,
                       backend_failures=sum(r['admitted'] and not r['success'] for r in rows),
                       in_flight=gate.in_flight, trace_count=len(arrivals),
                       finalized_offered=len(cohorts.requests),
                       unfinalized_cohorts=len(cohorts.buckets))
        summary['valid_plumbing'] = (len(rows) == len(arrivals) and gate.in_flight == 0
                                     and not cohorts.buckets and summary['successes'] > 0
                                     and summary['backend_failures'] == 0
                                     and summary['max_dispatch_lag_s'] <= config['max_dispatch_lag_seconds'])
        write_json(folder/'summary.json', summary)
        print(json.dumps(summary), flush=True)
        return summary
    finally:
        stop_ticks.set()
        ticker.cancel()
        await asyncio.gather(ticker, return_exceptions=True)
        for task in tasks.copy():
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        request_log.close()
        control_log.close()


async def run(args):
    if os.name != 'posix':
        raise RuntimeError('owned process-group runner requires Linux')
    cfg = json.loads(args.config.read_text())
    Config(**cfg['feedback'])
    profile_path = args.source / cfg['slo_source']
    profile = next(p for p in json.loads(profile_path.read_text())['profiles'] if p['name'] == cfg['profile'])
    for file in (args.model/'config.json', args.vllm, profile_path):
        if not file.is_file():
            raise ValueError(f'missing prerequisite {file}')
    arrivals, duration = trace(cfg)
    if len(arrivals) > 10000 or duration > 180:
        raise ValueError('smoke run exceeds fixed safety bound')
    gpu = subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader'], text=True)
    if gpu.strip():
        raise RuntimeError('GPU already has a compute process; refusing to start')
    # Refuse occupied local port instead of attaching to/killing an old server.
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', args.port))
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = dict(config=cfg, profile=profile, profile_sha256=digest(profile_path),
                    model_path=str(args.model), model_config_sha256=digest(args.model/'config.json'),
                    source_files={p.name: digest(p) for p in Path(__file__).parent.glob('*.py')},
                    frozen_dependency_files={name: digest(args.source/'src/slo_autotuner'/name)
                                             for name in ('executor.py', 'gateway.py', 'mixed.py', 'controller.py')},
                    trace_sha256=hashlib.sha256(json.dumps(arrivals, sort_keys=True).encode()).hexdigest(),
                    note='fixed then adaptive; shared warmed backend; development smoke only')
    command = [str(args.vllm), 'serve', str(args.model), '--host', '127.0.0.1', '--port', str(args.port),
               '--served-model-name', cfg['model_name'], '--dtype', 'float16', '--max-model-len', '4096',
               '--gpu-memory-utilization', '0.75', '--disable-uvicorn-access-log', '--no-enable-prefix-caching',
               '--enable-chunked-prefill', '--max-num-batched-tokens', '1024', '--max-num-seqs', '256',
               '--scheduling-policy', 'fcfs']
    manifest['command'] = command
    write_json(args.output/'manifest.json', manifest)
    write_json(args.output/'trace.json', arrivals)
    log = (args.output/'backend.log').open('x')
    process = None
    report = dict(status='failed', modes=[])
    try:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        write_json(args.output/'owned_process.json', dict(pid=process.pid, pgid=process.pid))
        url = f'http://127.0.0.1:{args.port}'
        async with asyncio.timeout(cfg['whole_run_timeout_seconds']):
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=cfg['request_timeout_seconds']+2),
                                             connector=aiohttp.TCPConnector(limit=128)) as session:
                deadline = time.monotonic()+cfg['health_timeout_seconds']
                while True:
                    if process.poll() is not None:
                        raise RuntimeError('owned backend exited during startup')
                    try:
                        async with session.get(url+'/health', timeout=aiohttp.ClientTimeout(total=2)) as response:
                            if response.status == 200:
                                break
                    except (aiohttp.ClientError, TimeoutError):
                        pass
                    if time.monotonic() >= deadline:
                        raise TimeoutError('backend startup deadline')
                    await asyncio.sleep(1)
                print('backend healthy; warming 4 requests', flush=True)
                for _ in range(4):
                    tracker = CompletionSseTracker()
                    async with session.post(url+'/v1/completions', json=dict(model=cfg['model_name'],
                                            prompt=list(range(100, 356)), max_tokens=64, ignore_eos=True,
                                            temperature=0, stream=True, return_token_ids=True)) as response:
                        if response.status != 200:
                            raise RuntimeError('warmup HTTP failure')
                        async for chunk in response.content.iter_any():
                            tracker.feed(chunk)
                        tracker.finish()
                        if not (tracker.seen_done and tracker.seen_token):
                            raise RuntimeError('warmup incomplete stream')
                for mode in ('fixed', 'adaptive'):
                    print(f'{mode}: starting {len(arrivals)} requests/{duration}s', flush=True)
                    report['modes'].append(await one_mode(mode, cfg, profile, arrivals, duration, session, url, args.output))
                    await asyncio.sleep(2)
                report['status'] = 'passed' if all(m['valid_plumbing'] for m in report['modes']) else 'invalid'
    except BaseException as exc:
        report['error'] = repr(exc)
        raise
    finally:
        if process is not None:
            # Group ID is created exclusively by this runner. Never use pkill.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(asyncio.to_thread(process.wait), 20)
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await asyncio.to_thread(process.wait)
            # Leader exit alone does not prove its engine children exited.
            await asyncio.sleep(2)
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                report['owned_group_stopped'] = True
            else:
                os.killpg(process.pid, signal.SIGKILL)
                await asyncio.sleep(2)
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    report['owned_group_stopped'] = True
                else:
                    report['owned_group_stopped'] = False
                    report['status'] = 'cleanup_requires_review'
            report['backend_exit_code'] = process.returncode
        log.close()
        write_json(args.output/'report.json', report)


async def entry(args):
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    await run(args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('pilot_config.json'))
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--vllm', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8019)
    asyncio.run(entry(parser.parse_args()))
