"""Independent bounded GPU cancellation probe; two timeouts, not a benchmark."""
import argparse
import asyncio
from dataclasses import asdict
import json
import math
from pathlib import Path
import re
import signal
import time
from types import SimpleNamespace
import aiohttp
from cohorts import ArrivalCohorts
from feedback import Config, Feedback
from hot_gate import HotAdmissionGate
from owned_backend import OwnedBackend, save
from transport import StreamingPilot
from resources import ResourceMonitor, summarize


def tagged_abort_lines(text, tag):
    # Require a full external ID plus the completion child suffix; reject prefix
    # matches such as case-1 matching case-10. Logging uses completion ID -0.
    pattern = re.compile(r'Request cmpl-' + re.escape(tag) + r'-0 aborted\.')
    return [line for line in text.splitlines() if pattern.search(line)]


def parse_metrics(raw):
    result = {}
    wanted = {'vllm:num_requests_running': 'running', 'vllm:num_requests_waiting': 'waiting',
              'vllm:generation_tokens_total': 'tokens'}
    for line in raw.splitlines():
        if line.startswith('#'):
            continue
        match = re.fullmatch(r'([^\s{]+)(\{.*\})?\s+([^\s]+)(?:\s+\S+)?', line)
        if not match:
            continue
        name, labels, value = match.groups()
        key = wanted.get(name)
        if name == 'vllm:request_success_total':
            reason = re.search(r'finished_reason="([^"]+)"', labels or '')
            if reason and reason[1] in ('abort', 'length'):
                key = reason[1]
        if key:
            number = float(value)
            if not math.isfinite(number) or number < 0:
                raise ValueError('invalid metric value')
            result[key] = result.get(key, 0)+number
    if set(result) != {'running', 'waiting', 'tokens', 'abort', 'length'}:
        raise ValueError(f'missing required metrics: {result.keys()}')
    return result


def verdict(before, after, samples, result, controls, stable_tokens):
    checks = dict(client_timeout=result.get('error') == 'TimeoutError' and result.get('outcome') == 'timeout',
                  generated_before_timeout=result.get('ttft_ms') is not None,
                  observed_running=any(s['metrics']['running'] >= 1 for s in samples),
                  abort_increment=after['abort']-before['abort'] == 1,
                  no_length_completion=after['length'] == before['length'],
                  work_stopped=after['running'] == 0 and after['waiting'] == 0,
                  token_work_below_full=0 < after['tokens']-before['tokens'] < 2048,
                  tokens_stable=stable_tokens,
                  decrease_applied=any(c['applied'] and c['decision'].reason == 'request_timeout' for c in controls))
    return checks


async def probe(backend, args):
    folder, url = args.output, backend.url
    counter = 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async def metrics(label):
            nonlocal counter
            async with session.get(url+'/metrics', timeout=aiohttp.ClientTimeout(total=2)) as response:
                response.raise_for_status()
                raw = await response.text()
            counter += 1
            with (folder/f'metrics-{counter:04d}-{label}.txt').open('x') as stream:
                stream.write(raw)
            return dict(at=time.monotonic(), metrics=parse_metrics(raw))

        async def idle(label, deadline_seconds=10):
            deadline = time.monotonic()+deadline_seconds
            observations = []
            stable_since = None
            last = None
            while time.monotonic() < deadline:
                row = await metrics(label)
                observations.append(row)
                m = row['metrics']
                if m['running'] == m['waiting'] == 0:
                    if last != m['tokens'] or stable_since is None:
                        stable_since = row['at']
                    elif row['at']-stable_since >= 2:
                        return row, observations
                else:
                    stable_since = None
                last = m['tokens']
                await asyncio.sleep(.1)
            raise TimeoutError('backend did not reach idle/token plateau within 10s')

        def pilot(timeout):
            f = Feedback(['long'], Config(settle_seconds=0))
            gate = HotAdmissionGate(f.rate)
            c = ArrivalCohorts({'long': (1000, 20000)}, origin=time.monotonic(), width=1, timeout=timeout)
            return StreamingPilot(SimpleNamespace(_lock=asyncio.Lock(), admission_gate=gate), f, c)

        def payload(tokens):
            return dict(model='cancel-probe', prompt=list(range(100, 356)), max_tokens=tokens,
                        ignore_eos=True, temperature=0, return_token_ids=True)

        for i in range(4):
            warm = await pilot(20).request(session, url+'/v1/completions', payload(64), 'long')
            if not warm['success']:
                raise RuntimeError('warmup failed')
        before, _ = await idle('control-before')
        control = await pilot(25).request(session, url+'/v1/completions', payload(2048), 'long')
        after, _ = await idle('control-after')
        control_pass = (control['success'] and control['e2el_ms'] > 3000
                        and after['metrics']['length']-before['metrics']['length'] == 1
                        and after['metrics']['tokens']-before['metrics']['tokens'] == 2048)
        save(folder/'full-length-control.json', dict(result=control, before=before, after=after, passed=control_pass))
        if not control_pass:
            raise RuntimeError('full-length control did not establish sufficiently long generation')
        cases = []
        for attempt in (1, 2):
            before, _ = await idle(f'{attempt}-before')
            p = pilot(1.5)
            tag = f'cancel-proof-case-{attempt}' if getattr(args, 'request_logs', False) else None
            log_offset = (folder/'backend.log').stat().st_size
            task = asyncio.create_task(p.request(session, url+'/v1/completions', payload(2048), 'long', request_tag=tag))
            during = []
            try:
                while not task.done():
                    during.append(await metrics(f'{attempt}-during'))
                    await asyncio.sleep(.1)
                result = await task
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            client_finished = time.monotonic()
            controls = await p.tick()
            after, post = await idle(f'{attempt}-after')
            checks = verdict(before['metrics'], after['metrics'], during, result, controls, True)
            abort_counter_check = checks['abort_increment']
            request_lines = []
            if tag is not None:
                with (folder/'backend.log').open('rb') as log:
                    log.seek(log_offset)
                    request_lines = tagged_abort_lines(log.read().decode(errors='replace'), tag)
                del checks['abort_increment']
                checks['tagged_abort_event'] = len(request_lines) == 1
            checks['gate_released'] = p.executor.admission_gate.in_flight == 0
            recovery = await pilot(20).request(session, url+'/v1/completions', payload(64), 'long')
            checks['recovery_request'] = recovery['success']
            async with session.get(url+'/health') as response:
                checks['healthy'] = response.status == 200
            idle_samples = [s for s in post if s['metrics']['running'] == 0 and s['metrics']['waiting'] == 0]
            record = dict(attempt=attempt, checks=checks, passed=all(checks.values()),
                          protocol='tagged-request-v2' if tag else 'counter-v1', request_tag=tag,
                          tagged_abort_lines=request_lines, abort_counter_check=abort_counter_check,
                          before=before, during=during, after=after, post=post, client_result=result,
                          client_finished_at=client_finished,
                          first_idle_observed_after_client_s=idle_samples[0]['at']-client_finished if idle_samples else None,
                          plateau_confirmed_after_client_s=after['at']-client_finished,
                          controls=[{**c, 'window': asdict(c['window']), 'decision': asdict(c['decision'])} for c in controls],
                          recovery=recovery)
            save(folder/f'case-{attempt}.json', record)
            cases.append(dict(attempt=attempt, passed=record['passed'], checks=checks))
            print(json.dumps(cases[-1]), flush=True)
        return dict(status='passed' if all(c['passed'] for c in cases) else 'failed', cases=cases)


async def main(args):
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    report = dict(status='failed')
    backend = OwnedBackend(args)
    monitor = ResourceMonitor(backend)
    monitoring = asyncio.create_task(monitor.watch()) if getattr(args, 'request_logs', False) else None
    try:
        async with asyncio.timeout(360):
            async with backend:
                monitor.phase = 'probe'
                print('backend healthy; testing full-length control then two timeout cases', flush=True)
                report = await probe(backend, args)
    except BaseException as exc:
        report['error'] = repr(exc)
        raise
    finally:
        if monitoring:
            monitoring.cancel()
            await asyncio.gather(monitoring, return_exceptions=True)
        if args.output.exists():
            if monitoring:
                save(args.output/'resources.json', dict(samples=monitor.rows, summary=summarize(monitor.rows), errors=monitor.errors))
            save(args.output/'report.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--vllm', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8021)
    parser.add_argument('--request-logs', action='store_true', help='new tagged-request protocol, preserves counter diagnostics')
    asyncio.run(main(parser.parse_args()))
