"""Shared, explicit file policy for public source distributions (stdlib only)."""
from pathlib import Path
import re

ROOT_FILES = {
    'README.md', 'pyproject.toml', '.gitignore', '.gitattributes',
    'LICENSE', 'LICENSE.md', 'CITATION.cff',
}
FOLDERS = {
    'src': {'.py'}, 'scripts': {'.py', '.sh'}, 'tests': {'.py'},
    'configs': {'.json'}, 'docs': {'.md', '.svg', '.png', '.json'},
    'environment': {'.txt', '.csv', '.lock'},
    'extensions': {'.py', '.md', '.json'},
    'tools': {'.mjs', '.js', '.json', '.yaml', '.md'},
    '.github': {'.yml', '.yaml'},
}
RESULT_PATTERNS = (
    '*_policy.json', '*_analysis.json', '*_rows.csv', '*_search.csv',
    '*_summary.csv', 'README.md', 'summary.csv',
    'poisson_boundary_aggregate.csv', 'workload_slo_calibration.csv',
    'workload_slo_calibration_extended.csv',
    'generalization_7b_capacity_audit.json',
    'generalization_7b_capacity_extension_amendment.json',
    'generalization_7b_slo_evidence.json', 'controller_replay.json',
    'controller_safety_scenarios.json', 'recovery_fault_scenarios.json',
)
EXCLUDED_PARTS = {'__pycache__', 'node_modules', '.venv', '.git', '.pytest_cache'}
MAX_FILE_BYTES = 10 * 1024 * 1024  # This source distribution needs no large files.
SENSITIVE = (
    ('private-key', re.compile(rb'-----BEGIN (?:[A-Z0-9]+ )?' + rb'PRIVATE KEY-----')),
    ('github-token', re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})')),
    ('cloud-login-host', re.compile(rb'connect\.[a-zA-Z0-9.-]+\.seetacloud\.com')),
    ('windows-user-path', re.compile(rb'(?i)[a-z]:[\\/]+Users[\\/]+[^\\/\s"<>]+')),
)


def public_files(root: Path) -> list[Path]:
    files = [root / name for name in ROOT_FILES if (root / name).is_file()]
    for folder, suffixes in FOLDERS.items():
        files.extend(p for p in (root / folder).rglob('*')
                     if p.is_file() and p.suffix in suffixes
                     and not EXCLUDED_PARTS.intersection(p.relative_to(root).parts))
    for pattern in RESULT_PATTERNS:
        files.extend(p for p in (root / 'results').glob(pattern) if p.is_file())
    return sorted(set(files))


def content_issues(path: Path, data: bytes) -> list[str]:
    issues = []
    if path.is_symlink():
        issues.append('symlink')
    if len(data) > MAX_FILE_BYTES:
        issues.append('oversized-source-file')
    issues.extend(label for label, pattern in SENSITIVE if pattern.search(data))
    return issues
