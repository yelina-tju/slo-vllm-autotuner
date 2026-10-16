"""Post-hoc boundary attribution; never changes the frozen verdict or denominator."""
import argparse
import json
from pathlib import Path


def summarize(rows, origin, profile, boundary=40):
    before = [r for r in rows if origin <= r['started_at_s'] < origin+boundary]
    successes = [r for r in before if r['success']]
    violated = [r for r in successes if r['ttft_ms'] > profile['ttft_slo_ms']
                or r['e2el_ms'] > profile['e2el_slo_ms']]
    crossing = [r for r in successes if r['completed_at_s'] >= origin+boundary]
    details = [dict(scheduled_at_s=r['scheduled_at_s'],
                    started_relative_s=r['started_at_s']-origin,
                    completed_relative_s=r['completed_at_s']-origin,
                    crosses_boundary=r['completed_at_s'] >= origin+boundary,
                    ttft_ms=r['ttft_ms'], e2el_ms=r['e2el_ms']) for r in violated]
    return dict(before_offered=len(before), before_successes=len(successes),
                crossing_successes=len(crossing), before_service_violations=len(violated),
                violations_completed_before_boundary=sum(not r['crosses_boundary'] for r in details),
                violations_crossing_boundary=sum(r['crosses_boundary'] for r in details),
                violating_requests=details)


def diagnostic(folder):
    cases = []
    for file in sorted(folder.glob('seed*-*/analysis.json')):
        analysis = json.loads(file.read_text())
        mode = 'adaptive_deadline' if analysis['arm'] == 'adaptive' else 'fixed'
        root = file.parent/mode
        meta = json.loads((root/'run_metadata.json').read_text())
        rows = [json.loads(line) for line in (root/'requests.jsonl').read_text().splitlines()]
        cases.append(dict(case=file.parent.name, frozen_before_healthy=analysis['before_healthy'],
                          **summarize(rows, meta['origin'], meta['profile'])))
    return dict(cases=cases, caveat='post-hoc descriptive boundary attribution, not a causal experiment; no exclusions or revised acceptance')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = diagnostic(args.folder)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
