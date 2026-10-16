"""Independent request accounting and conservative within-high-load recovery gate."""
import json
import math
from audit_alignment_pairs import audit_mode, p99, require
from pressure_analysis import queue_metrics


def stats(rows, duration, profile):
    good = [r for r in rows if r['success']]
    compliant = [r for r in good if r['ttft_ms'] <= profile['ttft_slo_ms'] and r['e2el_ms'] <= profile['e2el_slo_ms']]
    scheduled = [r for r in compliant if r['ttft_ms']+1000*r['dispatch_lag_s'] <= profile['ttft_slo_ms']
                 and r['e2el_ms']+1000*r['dispatch_lag_s'] <= profile['e2el_slo_ms']]
    pressure = max(p99([r['ttft_ms'] for r in good])/profile['ttft_slo_ms'],
                   p99([r['e2el_ms'] for r in good])/profile['e2el_slo_ms']) if good else None
    fraction = (len(good)-len(compliant))/len(good) if good else None
    return dict(offered=len(rows), successes=len(good), rejected=sum(not r['admitted'] for r in rows),
                failures=sum(r['admitted'] and not r['success'] for r in rows),
                compliant=len(compliant), violations=len(good)-len(compliant),
                scheduled_compliant=len(scheduled), scheduled_goodput=len(scheduled)/duration,
                pressure=pressure, violation_fraction=fraction,
                healthy=len(good) >= 30 and all(r['success'] for r in rows if r['admitted'])
                        and pressure <= 1 and fraction <= .01)


def recovery_gate(windows, actions):
    decreases = [a for a in actions if a['action'] == 'decrease' and 40 <= a['at'] < 200]
    if not decreases:
        return dict(recovered=False, reason='no within-high decrease', recovery_at=None)
    last = decreases[-1]
    eligible = [w for w in windows if w['start'] >= last['ready'] and w['end'] <= 200
                and w['emitted_at'] <= 200 and w['revision'] == last['revision']]
    for first, second in zip(eligible, eligible[1:]):
        if (first['healthy'] and second['healthy'] and first['epoch'] == second['epoch']
                and math.isclose(first['end'], second['start'], abs_tol=1e-6)
                and all(w['healthy'] for w in eligible if w['start'] >= first['start'])):
            return dict(recovered=True, reason='two consecutive fresh healthy windows during high load',
                        recovery_at=second['emitted_at'], last_decrease_at=last['at'],
                        recovery_from_high_start_s=second['emitted_at']-40,
                        recovery_after_last_action_s=second['emitted_at']-last['at'])
    return dict(recovered=False, reason='insufficient consecutive fresh healthy high-load windows', recovery_at=None)


def analyze_case(folder, trace, seed, arm):
    mode = 'adaptive_deadline' if arm == 'adaptive' else 'fixed'
    basic = audit_mode(folder/mode, trace, mode)
    read = lambda name: json.loads((folder/name).read_text(encoding='utf-8'))
    meta = read(f'{mode}/run_metadata.json')
    require(meta['duration'] == 240, 'recovery duration changed')
    origin, profile = meta['origin'], meta['profile']
    rows = [json.loads(line) for line in (folder/mode/'requests.jsonl').read_text().splitlines()]
    controls = [json.loads(line) for line in (folder/mode/'control.jsonl').read_text().splitlines()]
    phase_bounds = [('before', 0, 40), ('high', 40, 200), ('after', 200, 240)]
    phases = {name: stats([r for r in rows if start <= r['scheduled_at_s'] < end], end-start, profile)
              for name, start, end in phase_bounds}
    require(sum(p['offered'] for p in phases.values()) == len(rows), 'phase request loss')
    # Immutable grid, recomputed even if an adaptive accounting cohort mixed revisions.
    grid = []
    for start in range(0, 240, 20):
        members = [r for r in rows if origin+start <= r['started_at_s'] < origin+start+20]
        grid.append(dict(start=start, end=start+20, **stats(members, 20, profile)))
    actions, evidence = [], []
    for c in controls:
        w, audit = c['window'], c['audit']
        if c['applied'] is True:
            require(c['decision']['reason'] == 'observed_slo_or_backend_failure' if c['decision']['action'] == 'decrease'
                    else c['decision']['reason'] == 'fresh_headroom_and_demand', 'unexpected actuation reason')
            actions.append(dict(at=c['acknowledged_at']-origin, ready=c['settling_ready_at']-origin,
                                revision=c['feedback_revision'], action=c['decision']['action'],
                                rate=c['decision']['rate'], evidence_emitted_at=audit['emitted_at']-origin,
                                evidence_start=w['start']-origin, evidence_end=w['end']-origin))
        if audit.get('purpose') == 'evidence':
            members = [r for r in rows if w['start'] <= r['started_at_s'] < w['end']
                       and r['evidence_epoch'] == audit['epoch'] and r['admission_revision'] == w['revision']]
            evidence.append(dict(start=w['start']-origin, end=w['end']-origin,
                                 emitted_at=audit['emitted_at']-origin, epoch=audit['epoch'], revision=w['revision'],
                                 **stats(members, 20, profile)))
    samples = [json.loads(line) for line in (folder/'queue.jsonl').read_text().splitlines()]
    require(samples and all('error' not in s for s in samples), 'telemetry failure')
    for s in samples:
        require(s['metrics'] == queue_metrics(s['raw']), 'raw metrics mismatch')
        require(0 <= s['finished_at']-s['at'] <= .5, 'slow metrics scrape')
    during = [s for s in samples if origin <= s['at'] and s['finished_at'] <= origin+240]
    times = [s['at'] for s in during]
    require(len(times) >= 200 and times == sorted(times) and times[-1]-times[0] >= 230, 'telemetry coverage')
    require(max(b-a for a, b in zip(times, times[1:])) <= 3, 'telemetry gap')
    high_windows = [w for w in grid if 40 <= w['start'] and w['end'] <= 200]
    before_healthy = all(w['healthy'] for w in grid if w['end'] <= 40)
    lows_ok = all(w['healthy'] for w in high_windows) and phases['high']['healthy']
    highs_ok = sum(w['pressure'] is not None and w['pressure'] > 1 for w in high_windows) >= 2
    return dict(seed=seed, arm=arm, **basic, phases=phases, grid_windows=grid,
                evidence_windows_detail=evidence, actions=actions, before_healthy=before_healthy,
                low_anchor_reproduced=lows_ok, high_anchor_reproduced=highs_ok,
                recovery=recovery_gate(evidence, actions) if arm == 'adaptive' else None,
                telemetry_samples=len(during), sampled_max_waiting=max(s['metrics']['waiting'] for s in during),
                maximum_scrape_seconds=max(s['finished_at']-s['at'] for s in samples))


def verdict(cases):
    require(len(cases) == 6 and {(c['seed'], c['arm']) for c in cases} ==
            {(s, a) for s in (309, 310) for a in ('low', 'high', 'adaptive')}, 'incomplete paired recovery batch')
    pairs = []
    for seed in (309, 310):
        arms = {c['arm']: c for c in cases if c['seed'] == seed}
        low, high, adaptive = (arms[k] for k in ('low', 'high', 'adaptive'))
        baseline_ok = all(c['before_healthy'] for c in arms.values()) and low['low_anchor_reproduced'] and high['high_anchor_reproduced']
        pairs.append(dict(seed=seed, baselines_valid=baseline_ok,
                          recovery_pass=baseline_ok and adaptive['recovery']['recovered'],
                          adaptive_goodput=adaptive['goodput'], low_goodput=low['goodput'], high_goodput=high['goodput'],
                          adaptive_minus_low_goodput=adaptive['goodput']-low['goodput'],
                          adaptive_minus_high_goodput=adaptive['goodput']-high['goodput'],
                          adaptive_minus_low_rejections=adaptive['rejections']-low['rejections'],
                          adaptive_minus_high_violations=adaptive['completed_slo_violations']-high['completed_slo_violations']))
    status = ('inconclusive_baseline' if not all(p['baselines_valid'] for p in pairs) else
              'recovery_replicated' if all(p['recovery_pass'] for p in pairs) else 'recovery_not_replicated')
    return dict(status=status, pairs=pairs, caveat='adverse-initialization development experiment, not held-out superiority')
