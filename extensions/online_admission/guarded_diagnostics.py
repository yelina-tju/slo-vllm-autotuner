"""Supplementary timing/token diagnostics. Never changes the frozen verdict."""
import argparse
import json
import math
from pathlib import Path
from audit_generation_shape import generation_counts


def action_timing(record, origin):
    return dict(action=record['decision']['action'], rate=record['decision']['rate'],
                evidence_start=record['window']['start']-origin,
                evidence_end=record['window']['end']-origin,
                evidence_emitted_at=record['audit']['emitted_at']-origin,
                outcome_finalization_lag_s=record['audit']['emitted_at']-record['window']['end'],
                acknowledged_at=record['acknowledged_at']-origin,
                acknowledgment_after_evidence_ms=1000*(record['acknowledged_at']-record['audit']['emitted_at']),
                settling_ready_at=record['settling_ready_at']-origin)


def diagnostic(folder):
    cases = []
    for path in sorted(folder.glob('seed*-*/analysis.json')):
        result = json.loads(path.read_text(encoding='utf-8'))
        mode = 'adaptive_deadline' if result['arm'] == 'adaptive' else 'fixed'
        case = path.parent
        meta = json.loads((case/mode/'run_metadata.json').read_text())
        if meta['duration'] != 260:
            raise ValueError('guarded diagnostics require260s; do not relabel old data')
        rows = [json.loads(line) for line in (case/mode/'requests.jsonl').read_text().splitlines()]
        controls = [json.loads(line) for line in (case/mode/'control.jsonl').read_text().splitlines()]
        timings = [action_timing(c, meta['origin']) for c in controls if c['applied'] is True]
        bad = [r['completed_at_s']-meta['origin'] for r in rows if r['success'] and 60 <= r['scheduled_at_s'] < 220
               and (r['ttft_ms'] > meta['profile']['ttft_slo_ms'] or r['e2el_ms'] > meta['profile']['e2el_slo_ms'])]
        queue = [json.loads(line) for line in (case/'queue.jsonl').read_text().splitlines()]
        counts = [generation_counts(s['raw']) for s in queue]
        cases.append(dict(case=case.name, first_high_phase_violation_completed_at=min(bad) if bad else None,
                          action_timings=timings,
                          cumulative_generation_counts_monotone=all(b['count'] >= a['count'] for a, b in zip(counts, counts[1:])),
                          aggregate_mean_output64=all(math.isclose(s['tokens'], 64*s['count'], abs_tol=1e-6) for s in counts),
                          final_generation_count=counts[-1]['count'],
                          expected_completions_with_warmups=result['admitted_successes']+4))
    return dict(cases=cases, caveat='post-hoc diagnostic; not a new acceptance criterion or overhead ablation')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = diagnostic(args.folder)
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))


