"""Check the current Git publication boundary; never stage, commit or push."""
import argparse
import json
from pathlib import Path
import subprocess
from publication_files import content_issues, public_files


def inspect(root: Path) -> dict:
    root = root.resolve()
    # Per-command trust for this explicitly selected directory, not a global setting.
    result = subprocess.run(
        ['git', '-c', f'safe.directory={root.as_posix()}', 'ls-files',
         '--cached', '--others', '--exclude-standard', '-z'],
        cwd=root, capture_output=True, check=True,
    )
    candidates = sorted(set(result.stdout.decode('utf-8').strip('\0').split('\0')) - {''})
    allowed = {p.relative_to(root).as_posix() for p in public_files(root)}
    issues = []
    sizes = []
    for name in candidates:
        path = root / name
        if name not in allowed:
            issues.append({'path': name, 'issue': 'outside-publication-policy'})
            continue
        if not path.is_file():
            issues.append({'path': name, 'issue': 'missing-tracked-file'})
            continue
        data = path.read_bytes()
        issues.extend({'path': name, 'issue': issue} for issue in content_issues(path, data))
        sizes.append((len(data), name))
    for name in sorted(allowed - set(candidates)):
        issues.append({'path': name, 'issue': 'public-file-hidden-by-gitignore'})
    return {
        'status': 'passed' if not issues else 'failed',
        'files': len(candidates), 'total_bytes': sum(size for size, _ in sizes),
        'largest_files': [{'path': name, 'bytes': size} for size, name in sorted(sizes, reverse=True)[:5]],
        'issues': issues,
        'scope': 'Working-tree content and current Git candidate paths; stage after this check. '
                 'Not a history scanner or a guarantee that every possible secret is detected.',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    report = inspect(args.root)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report['status'] == 'passed' else 1)
