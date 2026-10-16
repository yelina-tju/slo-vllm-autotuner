"""CPU-only held-out proposal and prerequisite check; cannot launch GPU work."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
from audit_alignment_pairs import require
from recovery_plan import CONFIG as DEVELOPMENT

CONFIG = copy.deepcopy(DEVELOPMENT)
CONFIG['protocol'] = 'recovery-heldout401-402-proposal-v1'
CONFIG['orders'] = [dict(seed=401, arms=['low', 'high', 'adaptive']),
                    dict(seed=402, arms=['adaptive', 'high', 'low'])]
EVIDENCE_SHA = '3c852e87dfd3db788ca31bd23a236600c145830ae63270ade82830d174cd588c'


def validate(config):
    require(config == CONFIG, 'held-out proposal changed')


def plan():
    return [dict(seed=o['seed'], arm=arm) for o in CONFIG['orders'] for arm in o['arms']]


def make_trace(seed):
    require(seed in (401, 402), 'not a proposed held-out seed')
    rng, offset, result = random.Random(seed), 0, []
    for phase in CONFIG['phases']:
        at = rng.expovariate(phase['rps'])
        while at < phase['seconds']:
            result.append(dict(at=offset+at, prompt_seed=rng.randrange(2**31)))
            at += rng.expovariate(phase['rps'])
        offset += phase['seconds']
    require(0 < len(result) <= 14000, 'held-out trace cap')
    return result


def check_summary(result):
    require(result.get('status') == 'linked_evidence_verified', 'linked raw-evidence audit has not passed')
    require(result.get('new_cases') == 4 and result.get('preserved_cases') == 2, 'missing linked cases')
    require(result.get('offered_records') == 71364, 'unexpected development accounting total')
    require(result.get('verdict', {}).get('status') == 'recovery_replicated', 'development recovery not established')
    require([(c['seed'], c['arm']) for c in result.get('cases', [])] ==
            [(o['seed'], arm) for o in DEVELOPMENT['orders'] for arm in o['arms']], 'wrong development cases')


def prerequisites(archive, audit_file):
    missing = [str(p) for p in (archive, audit_file) if not p.is_file()]
    if missing:
        return dict(status='blocked_missing_evidence', missing=missing, gpu_launch_allowed=False)
    require(hashlib.sha256(archive.read_bytes()).hexdigest() == EVIDENCE_SHA, 'downloaded evidence hash mismatch')
    check_summary(json.loads(audit_file.read_text(encoding='utf-8')))
    return dict(status='summary_ready_requires_raw_reaudit_and_frozen_runner', gpu_launch_allowed=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    work = Path(__file__).resolve().parents[3]/'work'
    parser.add_argument('--archive', type=Path, default=work/'recovery-continuation-sep21-evidence.tar.gz')
    parser.add_argument('--audit', type=Path, default=work/'recovery-continuation-sep21-audit.json')
    args = parser.parse_args()
    traces = {s: make_trace(s) for s in (401, 402)}
    print(json.dumps(dict(config=CONFIG, cases=plan(), counts={s: len(t) for s, t in traces.items()},
                          prerequisites=prerequisites(args.archive, args.audit)), indent=2))
