"""Stdlib calibration analysis. No controller/model changes or GPU imports."""
import json
import math
import random
import re
from pathlib import Path
from audit_alignment_pairs import audit_mode, p99, require


def protocol_spec(config):
    specs = {'pressure-calibration-dev303-304-v1': ((303, 304), (3, 6, 9), 18),
             'pressure-calibration-dev305-306-v1': ((305, 306), (6, 12, 18), 36)}
    require(config.get('protocol') in specs, 'unknown frozen protocol')
    return specs[config['protocol']]


def validate(config):
    seeds, rates, offered = protocol_spec(config)
    require(config['orders'] == [dict(seed=seeds[0], rates=list(rates)), dict(seed=seeds[1], rates=list(reversed(rates)))],
            'calibration order must remain frozen')
    require(config['phases'] == [dict(seconds=120, rps=offered)], 'calibration trace bounds changed')
    require(config['cohort_seconds'] == 20 and config['request_timeout_seconds'] == 10,
            'calibration window/timeout changed')
    require(config['max_pending_tasks'] == 128 and config['max_dispatch_lag_seconds'] == .25,
            'driver bounds changed')


def make_trace(seed, offered_rps=18):
    require(offered_rps in (18, 36), 'offered rate outside frozen protocols')
    rng = random.Random(seed)
    at, rows = rng.expovariate(offered_rps), []
    while at < 120:
        rows.append(dict(at=at, prompt_seed=rng.randrange(2**31)))
        at += rng.expovariate(offered_rps)
    require(0 < len(rows) <= 10000, 'too many requests')
    return rows


def queue_metrics(raw):
    names = {'vllm:num_requests_running': 'running', 'vllm:num_requests_waiting': 'waiting'}
    found = {}
    for line in raw.splitlines():
        match = re.fullmatch(r'([^\s{]+)(?:\{.*\})?\s+([^\s]+)(?:\s+\S+)?', line)
        if not match or match[1] not in names:
            continue
        number = float(match[2])
        require(math.isfinite(number) and number >= 0, 'invalid queue metric')
        key = names[match[1]]
        found[key] = found.get(key, 0)+number
    require(set(found) == {'running', 'waiting'}, 'missing queue metrics')
    return found


def max_inflight(rows):
    events = [(r['started_at_s'], 1) for r in rows if r['admitted']]
    events += [(r['completed_at_s'], -1) for r in rows if r['admitted']]
    current = peak = 0
    for _, delta in sorted(events):
        current += delta
        peak = max(peak, current)
    require(current == 0, 'inflight accounting mismatch')
    return peak


def classify(window_pressures, whole_pressure, violation_fraction):
    require(len(window_pressures) == 6, 'expected six full evidence windows')
    require(all(math.isfinite(p) and p >= 0 for p in window_pressures), 'invalid pressure')
    require(math.isfinite(whole_pressure) and whole_pressure >= 0
            and math.isfinite(violation_fraction) and 0 <= violation_fraction <= 1, 'invalid whole-run measures')
    breaches = sum(p > 1 for p in window_pressures)
    if breaches == 0 and whole_pressure <= 1 and violation_fraction <= .01:
        return 'low'
    if breaches >= 2:
        return 'high'
    return 'ambiguous'


def select_pair(cases, seeds=(303, 304), rates=(3, 6, 9)):
    require(len(cases) == 6, 'six cases required before selection')
    require({(c['seed'], c['rate']) for c in cases} ==
            {(s, r) for s in seeds for r in rates}, 'duplicate/missing case')
    require(all(c['classification'] in ('low', 'high', 'ambiguous') for c in cases), 'unknown classification')
    lows = [r for r in rates if all(c['classification'] == 'low' for c in cases if c['rate'] == r)]
    highs = [r for r in rates if all(c['classification'] == 'high' for c in cases if c['rate'] == r)]
    pairs = [(lo, hi) for lo in lows for hi in highs if lo < hi]
    if not pairs:
        return dict(status='inconclusive', reason='no ordered low/high pair replicated in both development seeds')
    lo = max(p[0] for p in pairs)
    hi = min(p[1] for p in pairs if p[0] == lo)
    return dict(status='candidate_found', low_rate=lo, high_rate=hi,
                caveat='development candidate only; neither global capacity nor controller recovery validated')


def analyze_case(folder, trace, seed, rate):
    basic = audit_mode(folder/'fixed', trace, 'fixed')
    read = lambda name: json.loads((folder/name).read_text(encoding='utf-8'))
    meta = read('fixed/run_metadata.json')
    rows = [json.loads(line) for line in (folder/'fixed/requests.jsonl').read_text().splitlines()]
    controls = [json.loads(line) for line in (folder/'fixed/control.jsonl').read_text().splitlines()]
    samples = [json.loads(line) for line in (folder/'queue.jsonl').read_text().splitlines()]
    require(samples and all('error' not in s for s in samples), 'telemetry failed')
    origin, duration = meta['origin'], meta['duration']
    require(duration == 120 and meta['config']['fixed_rate'] == rate, 'wrong calibration rate/duration')
    for s in samples:
        require(s['metrics'] == queue_metrics(s['raw']), 'queue metric reconstruction mismatch')
        require(0 <= s['finished_at']-s['at'] <= .5, 'slow telemetry scrape')
    during = [s for s in samples if origin <= s['at'] and s['finished_at'] <= origin+duration]
    require(len(during) >= 100, 'insufficient queue telemetry')
    times = [s['at'] for s in during]
    require(times == sorted(times) and times[-1]-times[0] >= 110, 'telemetry coverage too short')
    require(max(b-a for a, b in zip(times, times[1:])) <= 3, 'telemetry gap')
    require(len(controls) == 6, 'expected six accounting windows')
    pressures = []
    for c in controls:
        cls = c['window']['classes'][meta['profile']['name']]
        require(cls['completed'] >= 30 and cls['failed'] == 0, 'insufficient/failed class outcomes')
        pressures.append(max(cls['ttft_ratio'], cls['e2e_ratio']))
    good = [r for r in rows if r['success']]
    ttft, e2e = p99([r['ttft_ms'] for r in good]), p99([r['e2el_ms'] for r in good])
    whole = max(ttft/meta['profile']['ttft_slo_ms'], e2e/meta['profile']['e2el_slo_ms'])
    fraction = basic['completed_slo_violations']/len(good)
    return dict(seed=seed, rate=rate, **basic, p99_ttft_ms=ttft, p99_e2e_ms=e2e,
                window_pressures=pressures, breached_windows=sum(p > 1 for p in pressures),
                violation_fraction=fraction, classification=classify(pressures, whole, fraction),
                telemetry_samples=len(during), sampled_max_running=max(s['metrics']['running'] for s in during),
                sampled_max_waiting=max(s['metrics']['waiting'] for s in during),
                peak_client_inflight=max_inflight(rows),
                maximum_scrape_seconds=max(s['finished_at']-s['at'] for s in samples))
