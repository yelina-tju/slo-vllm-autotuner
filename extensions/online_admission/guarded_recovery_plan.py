"""CPU-only phase-isolation proposal; no GPU execution or revised old verdict."""
import copy
import json
import random
from audit_alignment_pairs import require
from recovery_plan import CONFIG as DEVELOPMENT
from recovery_analysis import stats

CONFIG = copy.deepcopy(DEVELOPMENT)
CONFIG.update(protocol='guarded-recovery403-404-proposal-v1',
              phases=[dict(seconds=60, rps=6), dict(seconds=160, rps=72), dict(seconds=40, rps=6)],
              orders=[dict(seed=403, arms=['low', 'high', 'adaptive']),
                      dict(seed=404, arms=['adaptive', 'high', 'low'])])
REGIONS = [('initial', 0, 40), ('guard', 40, 60), ('high', 60, 220), ('after', 220, 260)]


def validate(config):
    require(config == CONFIG, 'guarded proposal changed')
    require(60-40 > config['request_timeout_seconds']+config['max_dispatch_lag_seconds'],
            'guard must exceed nominal timeout plus dispatch budget')


def make_trace(seed):
    require(seed in (403, 404), 'unregistered guarded seed')
    rng, offset, rows = random.Random(seed), 0, []
    for phase in CONFIG['phases']:
        at = rng.expovariate(phase['rps'])
        while at < phase['seconds']:
            rows.append(dict(at=offset+at, prompt_seed=rng.randrange(2**31)))
            at += rng.expovariate(phase['rps'])
        offset += phase['seconds']
    require(0 < len(rows) <= 14000, 'trace cap exceeded')
    return rows


def phase_accounting(rows, profile):
    """Scheduled-arrival partition; guard outcomes always remain in the total."""
    require(all(0 <= r['scheduled_at_s'] < 260 for r in rows), 'out-of-trace request')
    phases = {name: stats([r for r in rows if start <= r['scheduled_at_s'] < end], end-start, profile)
              for name, start, end in REGIONS}
    total = stats(rows, 260, profile)
    for field in ('offered', 'successes', 'rejected', 'failures', 'violations', 'scheduled_compliant'):
        require(sum(p[field] for p in phases.values()) == total[field], 'phase accounting loss')
    return dict(phases=phases, whole=total)


def initial_gate(rows, origin, profile):
    """Check actual finalization, not a timeout-based assumption about draining."""
    windows = []
    for start in (0, 20):
        members = [r for r in rows if origin+start <= r['started_at_s'] < origin+start+20]
        windows.append(dict(start=start, end=start+20, **stats(members, 20, profile)))
    members = [r for r in rows if origin <= r['started_at_s'] < origin+40]
    finalized = bool(members) and all(r['completed_at_s'] < origin+60 for r in members)
    return dict(healthy=finalized and all(w['healthy'] for w in windows),
                finalized_before_high=finalized, windows=windows)


def action_attribution(action):
    """Evidence membership and action time are different facts; keep both."""
    start, end = action['evidence_start'], action['evidence_end']
    require(start < end, 'invalid evidence interval')
    if end <= 60:
        label = 'pre_high_arrivals'
    elif start >= 60 and end <= 220:
        label = 'fully_high_arrivals'
    else:
        label = 'boundary_or_other'
    return dict(evidence_membership=label, acknowledged_during_high=60 <= action['at'] < 220)


if __name__ == '__main__':
    validate(CONFIG)
    print(json.dumps(dict(config=CONFIG, regions=REGIONS,
                          trace_counts={s: len(make_trace(s)) for s in (403, 404)},
                          gpu_launch_allowed=False, status='cpu_proposal_only'), indent=2))
