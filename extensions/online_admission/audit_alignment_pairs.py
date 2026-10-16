"""Stdlib per-request cohort membership and paired-result audit."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def require(ok, message):
    if not ok:
        raise ValueError(message)


def p99(values):
    values = sorted(values)
    return values[math.ceil(.99*len(values))-1] if values else None


def same(a, b):
    return a is b if a is None or b is None else math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-8)


def check_members(window, audit, members, profile):
    require(audit['offered'] == len(members), 'cohort offered count differs from request membership')
    admitted = [r for r in members if r['admitted']]
    require(audit['finalized'] == len(admitted), 'cohort admitted count mismatch')
    revisions = {r['admission_revision'] for r in members}
    mixed = len(revisions) > 1
    require(audit['mixed_revision'] == mixed, 'mixed-revision flag mismatch')
    timeouts = sum(r.get('outcome') == 'timeout' for r in admitted)
    require(audit['timed_out'] == timeouts, 'timeout count mismatch')
    require(window['timed_out'] == (0 if mixed else timeouts), 'actionable timeout count mismatch')
    if mixed:
        require(window['classes'] == {}, 'mixed evidence was not excluded')
        return
    if revisions:
        require(window['revision'] == next(iter(revisions)), 'wrong window revision')
    good = [r for r in admitted if r['success']]
    cls = window['classes'][profile['name']]
    require(cls['completed'] == len(good) and cls['failed'] == len(admitted)-len(good), 'class outcome mismatch')
    ttft = None if any(r.get('ttft_ms') is None for r in good) else p99([r['ttft_ms']/profile['ttft_slo_ms'] for r in good])
    e2e = p99([r['e2el_ms']/profile['e2el_slo_ms'] for r in good])
    require(same(ttft, cls['ttft_ratio']) and same(e2e, cls['e2e_ratio']), 'P99 mismatch')


def audit_mode(folder, trace, mode):
    meta = json.loads((folder/'run_metadata.json').read_text())
    summary = json.loads((folder/'summary.json').read_text())
    rows = [json.loads(line) for line in (folder/'requests.jsonl').read_text().splitlines()]
    controls = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
    origin, duration, cfg, profile = meta['origin'], meta['duration'], meta['config'], meta['profile']
    require(meta['mode'] == mode, 'mode mismatch')
    require(sorted(r['trace_id'] for r in rows) == list(range(len(trace))), 'missing/duplicated trace ID')
    require(len({r['request_id'] for r in rows}) == len(rows), 'duplicate request ID')
    for r in rows:
        require(r['scheduled_at_s'] == trace[r['trace_id']]['at'], 'changed arrival trace')
        require(origin <= r['started_at_s'] <= r['completed_at_s'], 'invalid request times')
        require(math.isfinite(r['dispatch_lag_s']) and 0 <= r['dispatch_lag_s'] <= cfg['max_dispatch_lag_seconds'], 'driver dispatch lag')
    require(summary['requests'] == len(rows) and summary['trace_count'] == len(trace), 'summary request count')
    require(summary['statuses'] == dict(Counter(str(r['status']) for r in rows)), 'status count')
    success = [r for r in rows if r['success']]
    compliant = [r for r in success if r['ttft_ms'] <= profile['ttft_slo_ms'] and r['e2el_ms'] <= profile['e2el_slo_ms']]
    scheduled = [r for r in compliant if r['ttft_ms']+r['dispatch_lag_s']*1000 <= profile['ttft_slo_ms']
                 and r['e2el_ms']+r['dispatch_lag_s']*1000 <= profile['e2el_slo_ms']]
    admission_lag = lambda r: max(0, r['started_at_s']-(origin+r['scheduled_at_s']))
    arrival_compliant = [r for r in compliant if r['ttft_ms']+1000*admission_lag(r) <= profile['ttft_slo_ms']
                         and r['e2el_ms']+1000*admission_lag(r) <= profile['e2el_slo_ms']]
    require(summary['successes'] == len(success) and summary['service_slo_compliant'] == len(compliant), 'success/SLO counts')
    require(summary['scheduled_slo_compliant'] == len(scheduled), 'scheduled SLO count')
    require(same(summary['scheduled_goodput'], len(scheduled)/duration), 'scheduled goodput mismatch')
    require(same(summary['service_goodput'], len(compliant)/duration), 'service goodput mismatch')
    require(summary['backend_failures'] == sum(r['admitted'] and not r['success'] for r in rows) == 0, 'backend failure')
    require(summary['valid_plumbing'] and summary['in_flight'] == summary['unfinalized_cohorts'] == 0, 'unfinalized run')

    epochs = {0: dict(ready=origin, revision=0)}
    applied = []
    rate = (cfg.get('fixed_rate', cfg['feedback'].get('initial', 3.0)) if mode == 'fixed'
            else cfg['feedback']['initial'])
    if mode == 'fixed':
        require(meta['alignment'] == 'fixed', 'static mode has adaptive alignment')
        require(same(meta.get('effective_initial_rate', rate), rate), 'static initial rate mismatch')
        require(all(r['admission_revision'] == 0 for r in rows), 'static request revision changed')
    revision = 0
    ready = origin
    for record in controls:
        if mode == 'fixed':
            require(record['decision'] is None and record['applied'] is None, 'static control attempted actuation')
            require(same(record['rate'], rate) and record['revision'] == 0, 'static rate/revision changed')
        if record['applied'] is not None:
            ack = record['acknowledged_at']
            require(ack >= record['audit']['emitted_at'], 'ack predates evidence')
            require(same(record['settling_ready_at'], ack+cfg['feedback']['settle_seconds']), 'wrong settling deadline')
            if record['applied']:
                require(ack < origin+duration, 'actuation after traffic deadline')
                require(record['window']['start'] >= ready, 'pre-settling evidence applied')
                require(record['window']['revision'] == revision, 'stale revision applied')
                target = record['decision']['rate']
                require(cfg['feedback']['minimum'] <= target <= cfg['feedback']['maximum'], 'rate bound')
                if record['decision']['action'] == 'increase':
                    require(same(target, min(cfg['feedback']['maximum'], rate+cfg['feedback']['additive_step'])), 'invalid additive step')
                elif record['decision']['action'] == 'decrease':
                    require(same(target, max(cfg['feedback']['minimum'], rate*cfg['feedback']['decrease_factor'])), 'invalid decrease')
                else:
                    raise ValueError('applied non-action')
                revision += 1
                rate = target
                applied.append(dict(at=ack-origin, rate=rate, reason=record['decision']['reason']))
            ready = record['settling_ready_at']
            require(record['feedback_revision'] == revision, 'ack revision mismatch')
            if mode == 'adaptive_deadline':
                epoch = record['current_evidence_epoch']
                require(epoch == len(epochs), 'epoch sequence mismatch')
                epochs[epoch] = dict(ready=ready, revision=revision)
    require(summary['transitions'] == len(applied) and same(summary['final_rate'], rate), 'final actuation state')

    accounted = []
    evidence_count = 0
    for c in controls:
        w, a = c['window'], c['audit']
        require(same(w['end']-w['start'], cfg['cohort_seconds']), 'shortened window')
        members = [r for r in rows if w['start'] <= r['started_at_s'] < w['end']]
        if a.get('purpose') == 'evidence':
            epoch = epochs[a['epoch']]
            require(w['start'] >= epoch['ready'], 'evidence starts before epoch deadline')
            grid = (w['start']-epoch['ready'])/cfg['cohort_seconds']
            require(math.isclose(grid, round(grid), rel_tol=1e-8, abs_tol=1e-6), 'misaligned epoch grid')
            members = [r for r in members if r['evidence_epoch'] == a['epoch'] and r['admission_revision'] == epoch['revision']]
            evidence_count += 1
        else:
            accounted.extend(r['trace_id'] for r in members)
        check_members(w, a, members, profile)
        require(same(w['offered_rps'], len(members)/cfg['cohort_seconds']), 'demand mismatch')
    require(sorted(accounted) == list(range(len(trace))), 'primary accounting omitted or double-counted requests')
    return dict(mode=mode, goodput=summary['scheduled_goodput'], service_goodput=summary['service_goodput'],
                arrival_timestamp_goodput=len(arrival_compliant)/duration,
                max_actual_admission_lag_s=max((admission_lag(r) for r in rows), default=0),
                admitted_successes=len(success), completed_slo_violations=len(success)-len(compliant),
                rejections=sum(not r['admitted'] for r in rows), applied=applied,
                accounting_requests=len(accounted), evidence_windows=evidence_count,
                reasons=dict(Counter(c['decision']['reason'] if c['decision'] is not None else 'static_accounting'
                                     for c in controls)))


def audit_batch(folder):
    manifest = json.loads((folder/'batch_manifest.json').read_text())
    report = json.loads((folder/'batch_report.json').read_text())
    require(report['status'] == 'passed' and len(report['completed']) == 4, 'batch incomplete')
    pairs = []
    for pair in manifest['config']['pairs']:
        directory = folder/f'seed{pair["seed"]}'
        trace = json.loads((directory/'trace.json').read_text())
        require(hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest()
                == json.loads((directory/'trace_hash.json').read_text())['sha256'], 'trace hash mismatch')
        results = {}
        for mode in pair['order']:
            require(json.loads((directory/f'{mode}-backend/cleanup.json').read_text())['stopped'], 'cleanup failed')
            require(len(json.loads((directory/f'{mode}-backend/warmup.json').read_text())) == 4, 'warmup count')
            results[mode] = audit_mode(directory/mode, trace, mode)
        fixed, anchored = results['adaptive_fixed'], results['adaptive_deadline']
        second = lambda r: r['applied'][1]['at'] if len(r['applied']) > 1 else None
        delta_second = second(anchored)-second(fixed) if second(anchored) is not None and second(fixed) is not None else None
        pairs.append(dict(seed=pair['seed'], order=pair['order'], modes=results,
                          goodput_delta=anchored['goodput']-fixed['goodput'], second_action_delta_s=delta_second))
    return dict(status='passed', pairs=pairs, mean_goodput_delta=sum(p['goodput_delta'] for p in pairs)/len(pairs),
                caveat='two development seeds; no held-out generalization or confidence interval claim')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit_batch(args.folder)
    if args.output:
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
