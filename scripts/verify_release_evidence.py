"""Offline archive-integrity and 7B safety evidence verification; no GPU needed.

Reads archives without extracting executable code. Optional output is a new
JSON report; existing reports are never overwritten.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

from audit_7b_fault_pair import audit as audit_pair
from audit_7b_restart_probe import audit as audit_restart

ARCHIVES = {
    'experiment017-final-evidence.tar.gz': '688c6dfd1ca4d291ad8611a76358fb58b5fabbe82e8ed346fb5346ab2bab332f',
    'fault7b-healthy-evidence.tar.gz': '7b4131677c51171a7071857bdc16986ae92652cead30d0c001b33f80da20cd31',
    'fault7b-delay-evidence.tar.gz': 'acdf32357adb528a15bdb4d1a33bb6b53465186e0f7d0fd7bf6e4db1eb74abcf',
    'fault7b-restart-evidence.tar.gz': 'a1135cb98e949c41d38bd0f2b34583470c30f7d9a80d8451ece2a01263ea11b0',
}


def verify(directory):
    if not __debug__:
        raise RuntimeError('Run without -O: legacy pair auditor uses assertions.')
    hashes = {}
    for name, expected in ARCHIVES.items():
        with (directory / name).open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected:
            raise ValueError(f'archive hash mismatch: {name}')
        hashes[name] = actual
    rows = []
    with tempfile.TemporaryDirectory(prefix='slo-evidence-') as temporary:
        root = Path(temporary)
        for name in ARCHIVES:
            if not name.startswith('fault7b-'):
                continue
            with tarfile.open(directory / name, 'r:gz') as archive:
                for member in archive:
                    parts = Path(member.name).parts
                    if (not member.isfile() or not parts or parts[0] != 'results'
                            or '..' in parts or '\\' in member.name
                            or not member.name.endswith('.json')):
                        continue
                    target = root.joinpath(*parts)
                    if not target.resolve().is_relative_to(root.resolve()):
                        raise ValueError('unsafe archive member')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as stream:
                        target.write_bytes(stream.read())
        for label in ('healthy_seed130', 'delay_seed131', 'delay_seed132'):
            for row in audit_pair(root / 'results' / f'fault7b_{label}'):
                row.pop('slo_violating_injected_ids', None)
                row['case'] = label
                rows.append(row)
        for label, fail in (('restart_ok_retry1', False), ('restart_fail', True)):
            row = audit_restart(root / 'results' / f'fault7b_{label}' / 'result.json', fail)
            row['path'] = f'results/fault7b_{label}/result.json'
            rows.append(row)
    return {'status': 'passed' if all(r['status'] == 'passed' for r in rows) else 'failed',
            'archives_sha256': hashes, 'safety_runs': rows,
            'scope': 'Archive integrity and eight safety-run contracts; not a GPU rerun or an independent causal proof.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = verify(args.archives)
    rendered = json.dumps(report, indent=2)
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(rendered + '\n')
    print(rendered)
    raise SystemExit(0 if report['status'] == 'passed' else 1)
