"""One-command offline recheck of the complete guarded evidence chain. No GPU/network."""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from audit_guarded_recovery import audit_batch

ARCHIVES = {
    'coarse-bracket-sep20-evidence.tar.gz': '86ca4f2f0aac4dcec1a4b2b36bf89f7b51713d8078d74a769c366232e26ab777',
    'recovery-sep21-attempt1-evidence.tar.gz': '8f42d36a89e91e240d3e31cee2e3d147a32a558add4cfc57eedd3ec10f2839ac',
    'recovery-continuation-sep21-evidence.tar.gz': '3c852e87dfd3db788ca31bd23a236600c145830ae63270ade82830d174cd588c',
    'heldout-sep21-evidence.tar.gz': 'b08ae203b7222bb134cb4db77c93c7689c18337741f89997d962c4d9a43cf324',
    'guarded-sep22-evidence.tar.gz': 'f513ee0660bd3be298bc756a171b9cf5a99f8bb838d16e4baac608c836999206',
    'heldout-v18-local-freeze.json': 'c776638a7a833b60e96e43c9426f88e3819467cd5438d9a15761b329087f499d',
    'guarded-v19-local-freeze.json': 'ca0fc0a572369180c7fd23915e1ed090e46d33d7d3985952ceffee07bb1c3562',
}


def check_files(work):
    for name, expected in ARCHIVES.items():
        with (work/name).open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != expected:
            raise ValueError(f'evidence hash mismatch: {name}')
    return dict(ARCHIVES)


def recheck(work):
    hashes = check_files(work)
    result_path = 'online-admission-pilot-results'
    old = work/'heldout-sep21-evidence'
    prefix = work/'recovery-sep21-attempt1-evidence'
    continuation = work/'recovery-continuation-sep21-evidence'
    guarded = work/'guarded-sep22-evidence'
    args = SimpleNamespace(
        heldout=old/result_path/'heldout401-402-attempt1',
        heldout_snapshot=old/'heldout-v18/online_admission',
        heldout_freeze=work/'heldout-v18-local-freeze.json',
        development=continuation/result_path/'recovery-dev309-310-continuation1',
        development_snapshot=continuation/'recovery-v17/online_admission',
        prefix=prefix/result_path/'recovery-dev309-310-attempt1',
        prefix_snapshot=prefix/'recovery-v15/online_admission',
        calibration=work/'coarse-bracket-sep20-evidence'/result_path/'coarse-dev307-308-attempt1')
    result = audit_batch(guarded/result_path/'guarded403-404-attempt1',
                         guarded/'guarded-v19/online_admission', args,
                         work/'guarded-v19-local-freeze.json')
    return dict(status=result['status'], verdict=result['verdict'],
                offered_records=result['offered_records'],
                source_hashes_verified=result['source_hashes_verified'], evidence_sha256=hashes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=Path(__file__).resolve().parents[3]/'work')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = recheck(args.work)
    if args.output:
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
