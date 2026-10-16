"""Guarded protocol with mandatory raw audit of the inconclusive predecessor."""
import copy
import hashlib
import json
from pathlib import Path
from audit_alignment_pairs import require
from audit_recovery import read, sha
from heldout_protocol import prepare as development_prepare, arguments as old_arguments, validate_runtime
from audit_heldout import audit_batch
from guarded_recovery_plan import CONFIG as PROPOSAL, make_trace

CONFIG = copy.deepcopy(PROPOSAL)
CONFIG['protocol'] = 'guarded-recovery403-404-v1'


def plan():
    return [dict(seed=o['seed'], arm=a) for o in CONFIG['orders'] for a in o['arms']]


def case_config(config, seed, arm):
    require(config == CONFIG and dict(seed=seed, arm=arm) in plan(), 'unregistered guarded case/config')
    cfg = copy.deepcopy(config)
    cfg['seed'] = seed
    if arm != 'adaptive':
        cfg['fixed_rate'] = 24 if arm == 'low' else 48
    return cfg, 'adaptive_deadline' if arm == 'adaptive' else 'fixed'


def arguments(parser):
    old_arguments(parser)
    for key in ('heldout', 'heldout-snapshot', 'heldout-freeze'):
        parser.add_argument('--'+key, type=Path, required=True)


def prepare(args, snapshot):
    previous = audit_batch(args.heldout, args.heldout_snapshot, args, args.heldout_freeze)
    require(previous['status'] == 'heldout_evidence_verified' and
            previous['verdict']['status'] == 'inconclusive_baseline', 'prior held-out record not preserved')
    old = read(args.heldout/'manifest.json')
    for name, digest in old['source_files'].items():
        require((snapshot/name).is_file() and sha(snapshot/name) == digest, f'frozen source changed: {name}')
    frozen, _ = development_prepare(args, snapshot)
    traces = {s: make_trace(s) for s in (403, 404)}
    frozen.update(config=CONFIG, cases=plan(),
                  trace_sha256={str(s): hashlib.sha256(json.dumps(t, sort_keys=True).encode()).hexdigest()
                                for s, t in traces.items()},
                  predecessor_report_sha256=sha(args.heldout/'report.json'),
                  predecessor_freeze_sha256=sha(args.heldout_freeze),
                  predecessor_verdict='inconclusive_baseline')
    return frozen, traces
