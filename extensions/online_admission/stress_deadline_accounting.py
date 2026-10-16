"""Deterministic CPU stress/oracle; not loaded by the running GPU batch."""
import argparse
import json
import random
from pathlib import Path
from deadline_cohorts import DeadlineCohorts


def require(ok, message):
    if not ok:
        raise ValueError(message)


def scenario(seed, count=250):
    rng = random.Random(seed)
    c = DeadlineCohorts({'short': (100, 200), 'long': (300, 600)}, width=1, timeout=2, max_requests=count)
    expected = {}
    events = []
    for i in range(count):
        start = rng.random()*20
        admitted = rng.random() < .7
        elapsed = rng.uniform(.01, 4)
        row = dict(start=start, admitted=admitted, elapsed=elapsed,
                   shape=rng.choice(['short', 'long']), success=rng.random() > .08)
        expected[i] = row
        events.append((start, 0, i))
        if admitted:
            events.append((start+elapsed, 1, i))
    for i in range(6):
        events.append((3.05+i*3.05, 2, rng.choice([0, 1])))
    for i in range(131):
        events.append((i*.2, 3, 0))
    accounted = []
    evidence_windows = 0
    for now, kind, value in sorted(events):
        if kind == 0:
            r = expected[value]
            r.update(revision=c.evidence_revision, epoch=c.epoch)
            c.begin(value, now, r['shape'], r['revision'], r['admitted'])
        elif kind == 1:
            r = expected[value]
            accepted = c.end(value, now, r['success'], 10, r['elapsed']*1000)
            require(accepted == (r['elapsed'] < 2), 'late completion changed timeout outcome')
        elif kind == 2:
            c.reset_evidence(now+.7, c.evidence_revision+value, now)
        else:
            for w, a in c.advance(now, c.evidence_revision):
                ids = [i for i, r in expected.items() if w.start <= r['start'] < w.end]
                if a['purpose'] == 'evidence':
                    ids = [i for i in ids if expected[i]['epoch'] == a['epoch'] and expected[i]['revision'] == w.revision]
                    evidence_windows += 1
                else:
                    accounted.extend(ids)
                require(a['offered'] == len(ids), 'offered count lost or duplicated')
                admitted = [expected[i] for i in ids if expected[i]['admitted']]
                require(a['finalized'] == len(admitted), 'admitted count lost')
                require(a['timed_out'] == sum(r['elapsed'] >= 2 for r in admitted), 'timeout count lost')
                mixed = len({expected[i]['revision'] for i in ids}) > 1
                require(a['mixed_revision'] == mixed, 'revision contamination')
                if mixed:
                    require(w.classes == {}, 'mixed evidence retained')
                else:
                    for shape, cls in w.classes.items():
                        group = [r for r in admitted if r['shape'] == shape]
                        good = sum(r['success'] and r['elapsed'] < 2 for r in group)
                        require(cls.completed == good and cls.failed == len(group)-good, 'class outcome mismatch')
    require(sorted(accounted) == list(range(count)), 'primary ledger not conserved')
    require(len(c.requests) == count and not c.buckets, 'unfinished primary accounting')
    return dict(seed=seed, requests=count, epochs=c.epoch+1, evidence_windows=evidence_windows,
                timeouts=sum(r['admitted'] and r['elapsed'] >= 2 for r in expected.values()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    cases = [scenario(seed) for seed in range(100)]
    report = dict(status='passed', scenarios=len(cases), requests=sum(c['requests'] for c in cases),
                  timeout_outcomes=sum(c['timeouts'] for c in cases), cases=cases,
                  note='CPU event-accounting stress; no throughput or statistical reliability claim')
    if args.output:
        with args.output.open('x') as stream:
            json.dump(report, stream, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}))
