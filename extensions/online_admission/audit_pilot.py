"""Read-only stdlib audit of a completed smoke run; optional new report file."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(folder):
    manifest = json.loads((folder/'manifest.json').read_text())
    trace = json.loads((folder/'trace.json').read_text())
    require(hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest() == manifest['trace_sha256'], 'trace hash mismatch')
    report = json.loads((folder/'report.json').read_text())
    cfg, profile = manifest['config'], manifest['profile']
    duration = sum(p['seconds'] for p in cfg['phases'])
    results = []
    for mode in ('fixed', 'adaptive'):
        rows = [json.loads(line) for line in (folder/mode/'requests.jsonl').read_text().splitlines()]
        controls = [json.loads(line) for line in (folder/mode/'control.jsonl').read_text().splitlines()]
        summary = json.loads((folder/mode/'summary.json').read_text())
        require(sorted(r['trace_id'] for r in rows) == list(range(len(trace))), f'{mode}: missing/duplicate request')
        require(len({r['request_id'] for r in rows}) == len(rows), 'duplicate runtime ID')
        for row in rows:
            require(row['scheduled_at_s'] == trace[row['trace_id']]['at'], 'schedule mismatch')
            require(math.isfinite(row['dispatch_lag_s']) and row['dispatch_lag_s'] >= 0, 'invalid scheduling lag')
            if row['success']:
                require(row['admitted'] and row['status'] == 200 and row['outcome'] == 'success', 'invalid success')
                require(row['ttft_ms'] is not None and 0 <= row['ttft_ms'] <= row['e2el_ms'] < float('inf'), 'invalid success latency')
        def compliant(r, lag):
            return r['success'] and r['ttft_ms']+lag <= profile['ttft_slo_ms'] and r['e2el_ms']+lag <= profile['e2el_slo_ms']
        service = sum(compliant(r, 0) for r in rows)
        scheduled = sum(compliant(r, r['dispatch_lag_s']*1000) for r in rows)
        require(summary['requests'] == len(rows), 'request count mismatch')
        require(summary['statuses'] == dict(Counter(str(r['status']) for r in rows)), 'status mismatch')
        require(summary['service_slo_compliant'] == service, 'SLO count mismatch')
        require(summary['scheduled_slo_compliant'] == scheduled, 'scheduled SLO mismatch')
        require(math.isclose(summary['scheduled_goodput'], scheduled/duration), 'goodput mismatch')
        require(math.isclose(summary['service_goodput'], service/duration), 'service goodput mismatch')
        accounting = [c for c in controls if c['audit'].get('purpose') != 'evidence']
        windows = [c['window'] for c in accounting]
        require(all(a['end'] <= b['start'] for a, b in zip(windows, windows[1:])), 'overlapping windows')
        require(sum(c['audit']['offered'] for c in accounting) == len(trace), 'incomplete cohort accounting')
        applied = [c for c in controls if c['applied']]
        require(summary['transitions'] == len(applied), 'transition count mismatch')
        for c in applied:
            require(cfg['feedback']['minimum'] <= c['decision']['rate'] <= cfg['feedback']['maximum'], 'rate outside bounds')
        if mode == 'fixed':
            require(not applied and all(c['rate'] == cfg['feedback']['initial'] for c in controls), 'fixed baseline changed')
        results.append(dict(mode=mode, summary=summary,
                            reasons=dict(Counter(c['decision']['reason'] for c in controls if c['decision'])),
                            applied=[dict(at=c['observed_at_s'], rate=c['decision']['rate'], reason=c['decision']['reason']) for c in applied],
                            cohort_evidence=[dict(start=c['window']['start'], classes=c['window']['classes']) for c in controls]))
    require(report.get('owned_group_stopped') is True, 'owned process cleanup not confirmed')
    return dict(accounting_audit='passed', run_status=report['status'],
                note='development smoke; not randomized performance evidence', modes=results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.folder)
    if args.output:
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps({**result, 'modes': [{k: v for k, v in m.items() if k != 'cohort_evidence'} for m in result['modes']]}, indent=2))
