"""Frozen held-out configuration and raw-development prerequisite gate."""
import copy
import hashlib
import json
from pathlib import Path
from audit_alignment_pairs import require
from audit_recovery import read, sha
from audit_recovery_continuation import audit
from heldout_plan import CONFIG as PROPOSAL, plan, make_trace, check_summary

CONFIG = copy.deepcopy(PROPOSAL)
CONFIG['protocol'] = 'recovery-heldout401-402-v1'


def case_config(config, seed, arm):
    require(config == CONFIG, 'held-out configuration changed')
    require(dict(seed=seed, arm=arm) in plan(), 'unregistered held-out case')
    result = copy.deepcopy(config)
    result['seed'] = seed
    if arm != 'adaptive':
        result['fixed_rate'] = 24 if arm == 'low' else 48
    return result, 'adaptive_deadline' if arm == 'adaptive' else 'fixed'


def prepare(args, snapshot):
    development = audit(args.development, args.development_snapshot,
                        args.prefix, args.prefix_snapshot, args.calibration)
    check_summary(development)
    manifest = read(args.development/'manifest.json')
    for name, digest in manifest['source_files'].items():
        require((snapshot/name).is_file() and sha(snapshot/name) == digest,
                f'frozen development source changed: {name}')
    traces = {s: make_trace(s) for s in (401, 402)}
    frozen = dict(config=CONFIG, cases=plan(),
                  limits=dict(case_seconds=600, batch_seconds=3900, retries=0),
                  source_files={p.name: sha(p) for p in snapshot.glob('*.py')},
                  trace_sha256={str(s): hashlib.sha256(json.dumps(t, sort_keys=True).encode()).hexdigest()
                                for s, t in traces.items()},
                  development_report_sha256=sha(args.development/'report.json'),
                  development_manifest_sha256=sha(args.development/'manifest.json'),
                  prefix_report_sha256=sha(args.prefix/'report.json'),
                  profile=manifest['profile'], profile_sha256=manifest['profile_sha256'],
                  frozen_dependencies=manifest['frozen_dependencies'],
                  calibration_report_sha256=manifest['calibration_report_sha256'],
                  backend=read(args.prefix/'seed309-low/backend/manifest.json'))
    return frozen, traces


def arguments(parser):
    for key in ('development', 'development-snapshot', 'prefix', 'prefix-snapshot', 'calibration'):
        parser.add_argument('--'+key, type=Path, required=True)


def validate_runtime(args, frozen):
    require(sha(args.source/CONFIG['slo_source']) == frozen['profile_sha256'], 'SLO changed')
    require({n: sha(args.source/'src/slo_autotuner'/n) for n in frozen['frozen_dependencies']}
            == frozen['frozen_dependencies'], 'V1 source changed')
    require(sha(args.model/'config.json') == frozen['backend']['model_config_sha256'], 'model changed')
