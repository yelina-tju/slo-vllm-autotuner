"""CPU timing analysis only; does not predict changed-policy goodput."""
import argparse
import json
import math
from pathlib import Path


def timing(ready, origin, width, confirmations):
    if not all(math.isfinite(x) for x in (ready, origin, width)) or width <= 0 or ready < origin:
        raise ValueError('invalid grid')
    if type(confirmations) is not int or confirmations < 1:
        raise ValueError('invalid confirmation count')
    start = origin + math.ceil((ready-origin)/width)*width
    return dict(first_eligible_start=start, alignment_wait=start-ready,
                earliest_confirmation=start+confirmations*width,
                ideal_reanchored_confirmation=ready+confirmations*width)


def analyze(folder):
    manifest = json.loads((folder/'manifest.json').read_text())
    controls = [json.loads(line) for line in (folder/'adaptive/control.jsonl').read_text().splitlines()]
    cfg = manifest['config']
    origin = controls[0]['window']['start']
    change = next(c for c in controls if c['applied'])
    # Exact acknowledgement timestamp was not logged. Bound it by the tick's
    # initial observation and the post-application log timestamp.
    ack_bounds = [change['audit']['emitted_at'], origin+change['observed_at_s']]
    predictions = [timing(t+cfg['feedback']['settle_seconds'], origin,
                          cfg['cohort_seconds'], cfg['feedback']['confirmations']) for t in ack_bounds]
    return dict(method='fixed-grid eligibility geometry; no counterfactual throughput claim',
                acknowledgement_bounds_relative=[t-origin for t in ack_bounds],
                alignment_wait_bounds=sorted(p['alignment_wait'] for p in predictions),
                grid_confirmation_relative=predictions[0]['earliest_confirmation']-origin,
                sweep=[dict(phase=p, **timing(p+20, 0, 20, 2)) for p in (0, .001, .1, 1, 5, 10, 19.999)],
                caution='reanchoring would change cohort membership/sample counts; not an experimentally verified improvement')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = analyze(args.folder)
    if args.output:
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
