"""Pure sequential plan. Replays history and rejects out-of-plan extra work."""
import random
from audit_alignment_pairs import require
from feedback import Config


def validate(config):
    require(config['protocol'] == 'coarse-bracket-dev307-308-v1', 'unknown coarse protocol')
    require((config['coarse_seed'], config['confirmation_seed']) == (307, 308), 'seeds changed')
    require(config['rates'] == [18, 24, 36, 48], 'coarse cap/rates changed')
    require(config['phases'] == [dict(seconds=120, rps=72)], 'traffic changed')
    for key, value in dict(cohort_seconds=20, request_timeout_seconds=10, tick_seconds=.25,
                           max_dispatch_lag_seconds=.25, max_pending_tasks=128).items():
        require(config[key] == value, f'bound changed: {key}')
    Config(**config['feedback'])


def make_trace(seed):
    require(seed in (307, 308), 'unregistered seed')
    rng = random.Random(seed)
    at, rows = rng.expovariate(72), []
    while at < 120:
        rows.append(dict(at=at, prompt_seed=rng.randrange(2**31)))
        at += rng.expovariate(72)
    require(0 < len(rows) <= 10000, 'trace exceeds request cap')
    return rows


def next_step(history):
    require(len(history) <= 6, 'too many completed cases')
    index, low, high = 0, None, None

    def finish(status, reason):
        require(index == len(history), 'extra cases after terminal decision')
        return dict(kind='stop', status=status, reason=reason, low_rate=low, high_rate=high)

    def consume(seed, rate):
        nonlocal index
        row = history[index]
        require((row['seed'], row['rate']) == (seed, rate), 'case order differs from sequential plan')
        require(row['classification'] in ('low', 'high', 'ambiguous'), 'invalid case cannot advance plan')
        index += 1
        return row['classification']

    for rate in (18, 24, 36, 48):
        if index == len(history):
            return dict(kind='run', seed=307, rate=rate)
        label = consume(307, rate)
        if label == 'low':
            low = rate
        elif label == 'high':
            high = rate
            break
    if high is None:
        return finish('inconclusive', 'cap reached without HIGH')
    if low is None:
        return finish('inconclusive', 'first HIGH has no earlier within-trace LOW')
    for rate, expected in ((high, 'high'), (low, 'low')):
        if index == len(history):
            return dict(kind='run', seed=308, rate=rate)
        if consume(308, rate) != expected:
            return finish('inconclusive', f'{expected} classification did not replicate')
    return finish('candidate_found', 'LOW/HIGH replicated in both development seeds')


async def drive(run_case, completed, checkpoint):
    while True:
        action = next_step(completed)
        if action['kind'] == 'stop':
            return action
        result = await run_case(action['seed'], action['rate'])
        # Failed callback never appends a completed case or schedules another run.
        candidate = completed+[result]
        next_step(candidate)  # validate returned identity/label before checkpoint
        completed.append(result)
        checkpoint(completed)
