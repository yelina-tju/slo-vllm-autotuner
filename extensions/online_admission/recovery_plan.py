"""Frozen recovery development design; no GPU or HTTP dependencies."""
import random
from audit_alignment_pairs import require

FEEDBACK = dict(minimum=1, maximum=48, initial=48, additive_step=1,
                decrease_factor=.7, grow_below=.8, demand_fraction=.9,
                minimum_samples=30, confirmations=2, settle_seconds=20)
CONFIG = dict(protocol='recovery-dev309-310-v1', model_name='qwen2.5-1.5b',
              profile='balanced', slo_source='configs/workload_profiles.json',
              phases=[dict(seconds=40, rps=6), dict(seconds=160, rps=72), dict(seconds=40, rps=6)],
              cohort_seconds=20, request_timeout_seconds=10, tick_seconds=.25,
              max_dispatch_lag_seconds=.25, max_pending_tasks=128, feedback=FEEDBACK,
              orders=[dict(seed=309, arms=['low', 'high', 'adaptive']),
                      dict(seed=310, arms=['adaptive', 'high', 'low'])])


def validate(config):
    require(config == CONFIG, 'recovery configuration differs from frozen protocol')


def plan(config):
    validate(config)
    return [dict(seed=o['seed'], arm=arm) for o in config['orders'] for arm in o['arms']]


def case_config(config, seed, arm):
    validate(config)
    require(seed in (309, 310) and arm in ('low', 'high', 'adaptive'), 'unknown recovery case')
    cfg = {**config, 'seed': seed}
    if arm != 'adaptive':
        cfg['fixed_rate'] = 24 if arm == 'low' else 48
    return cfg, 'adaptive_deadline' if arm == 'adaptive' else 'fixed'


def make_trace(seed):
    require(seed in (309, 310), 'unregistered recovery seed')
    rng, offset, rows = random.Random(seed), 0, []
    for phase in CONFIG['phases']:
        at = rng.expovariate(phase['rps'])
        while at < phase['seconds']:
            rows.append(dict(at=offset+at, prompt_seed=rng.randrange(2**31)))
            at += rng.expovariate(phase['rps'])
        offset += phase['seconds']
    require(0 < len(rows) <= 14000, 'recovery trace exceeds frozen cap')
    return rows
