"""Ideal admission-only replay, not a backend or SLO performance prediction."""
import argparse
import json
import math
from pathlib import Path


def replay(times, rate, burst_seconds=.25):
    if not all(math.isfinite(v) and v > 0 for v in (rate, burst_seconds)):
        raise ValueError('positive finite gate settings required')
    capacity = max(1., rate*burst_seconds)
    tokens, previous = capacity, 0.
    accepted = []
    for index, at in enumerate(times):
        if not math.isfinite(at) or at < previous:
            raise ValueError('arrival times must be finite nonnegative and sorted')
        tokens = min(capacity, tokens+(at-previous)*rate)
        previous = at
        if tokens >= 1:
            tokens -= 1
            accepted.append(index)
    return dict(offered=len(times), accepted=len(accepted), rejected=len(times)-len(accepted),
                accepted_ids=accepted, rate=rate, capacity=capacity)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('reference', type=Path)
    args = parser.parse_args()
    rows = []
    for seed in (202, 203):
        trace = json.loads((args.reference/f'seed{seed}/trace.json').read_text())
        for rate in (3, 6):
            result = replay([r['at'] for r in trace], rate)
            result.pop('accepted_ids')
            rows.append(dict(seed=seed, **result))
    print(json.dumps(dict(cases=rows,
        caveat='ideal scheduled timestamps; actual scheduling jitter may change admissions; no SLO or GPU prediction'), indent=2))
