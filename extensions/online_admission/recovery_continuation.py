"""Explicitly reviewed continuation of one pinned prelaunch failure, never generic resume."""
from pathlib import Path
from audit_alignment_pairs import require
from audit_recovery import audit, read, sha
from recovery_plan import CONFIG, plan

PREFIX_REPORT = 'f94479aa174bae251fe18c7a0b84e42d27305912960342371b728ca6d737ed34'
PREFIX_MANIFEST = '267c96206244a02d04ff0b050e520ba1ecaaab238d71f94b0018a8c8e17871e2'
REPAIRED_OWNER = '33287d53e459a8950fbc4efcf1e8f7f001a2bdcba49d32c15f6f77833f7ebaaa'


def remaining_cases(prefix_cases):
    identities = [dict(seed=c['seed'], arm=c['arm']) for c in prefix_cases]
    require(identities == plan(CONFIG)[:2], 'only the exact two completed controls may be skipped')
    return plan(CONFIG)[2:]


def reviewed_changes(old, new):
    require(set(old) <= set(new), 'prior source file removed')
    changed = {name for name in old if old[name] != new[name]}
    require(changed == {'owned_backend.py', 'run_recovery.py'}, 'unreviewed change to frozen execution/scoring code')
    require(new['owned_backend.py'] == REPAIRED_OWNER, 'port repair differs from reviewed code')
    return {name: dict(before=old[name], after=new[name]) for name in sorted(changed)}


def prepare(prefix, prefix_snapshot, calibration, snapshot):
    require(sha(prefix/'report.json') == PREFIX_REPORT and sha(prefix/'manifest.json') == PREFIX_MANIFEST,
            'wrong or changed prefix evidence')
    checked = audit(prefix, prefix_snapshot, calibration, allow_partial=True)
    require(checked['status'] == 'completed_prefix_verified', 'prefix not verified')
    remaining = remaining_cases(checked['cases'])
    previous = read(prefix/'manifest.json')
    current = {p.name: sha(p) for p in snapshot.glob('*.py')}
    changes = reviewed_changes(previous['source_files'], current)
    traces = {seed: read(prefix/f'trace-{seed}.json') for seed in (309, 310)}
    link = dict(protocol='recovery-continuation-after-port-preflight-v1',
                prefix_report_sha256=PREFIX_REPORT, prefix_manifest_sha256=PREFIX_MANIFEST,
                trace_file_sha256={str(seed): sha(prefix/f'trace-{seed}.json') for seed in (309, 310)},
                skipped_cases=plan(CONFIG)[:2], remaining_cases=remaining, reviewed_source_changes=changes,
                caveat='linked interrupted development batch; not an uninterrupted paired experiment')
    return dict(link=link, remaining=remaining, prefix_cases=checked['cases']), traces
