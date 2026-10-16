"""Validate installed source release without a GPU; save command evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def validate(root, bash='bash'):
    manifest = json.loads((root / 'SOURCE_MANIFEST.json').read_text())
    for name, expected in manifest.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'manifest mismatch: {name}')
    commands = [[sys.executable, '-m', 'pip', 'check'],
                [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                [sys.executable, '-m', 'unittest', 'discover', '-s', 'extensions/online_admission', '-p', 'test_*.py', '-q'],
                [sys.executable, 'scripts/check_7b_fault_contract.py'],
                [sys.executable, 'extensions/online_admission/replay.py'],
                [sys.executable, 'scripts/run_7b_restart_probe.py', '--help'],
                [sys.executable, 'scripts/run_7b_fault_pairs.py', '--help']]
    commands.extend([bash, '-n', str(p)] for p in sorted((root / 'scripts').glob('*.sh')))
    results = []
    for command in commands:
        try:
            run = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=180)
            results.append({'command': command, 'returncode': run.returncode,
                            'stdout': run.stdout, 'stderr': run.stderr})
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append({'command': command, 'returncode': 1,
                            'stdout': '', 'stderr': str(exc)})
    return {'status': 'passed' if all(r['returncode'] == 0 for r in results) else 'failed',
            'manifest_files': len(manifest), 'python': sys.version, 'checks': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bash', default='bash', help='Bash executable, e.g. Git for Windows bash.exe')
    args = parser.parse_args()
    report = validate(args.root.resolve(), args.bash)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['status'] == 'passed' else 1)
