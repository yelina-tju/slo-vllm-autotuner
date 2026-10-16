"""Read-only reconstruction of the bounded sequential experiment and checkpoints."""
import argparse
import hashlib
import json
from pathlib import Path
from audit_alignment_pairs import require
from audit_static_endpoints import normalized_command
from coarse_plan import validate, make_trace, next_step
from pressure_analysis import analyze_case


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(folder, snapshot, static_reference):
    manifest, report = read(folder/'manifest.json'), read(folder/'report.json')
    config = manifest['config']
    validate(config)
    require(report['status'] == 'passed', 'batch failed or incomplete')
    require(read(snapshot/'coarse_config.json') == config, 'config content changed')
    require(sha(snapshot/'coarse_config.json') == manifest['config_sha256'], 'config hash changed')
    require(set(manifest['source_files']) == {p.name for p in snapshot.glob('*.py')}, 'snapshot file set mismatch')
    for name, expected in manifest['source_files'].items():
        require(Path(name).name == name, 'invalid source name')
        require(sha(snapshot/name) == expected, f'source hash mismatch: {name}')
    previous = read(static_reference/'manifest.json')
    require(manifest['profile'] == previous['profile'] and
            manifest['profile_sha256'] == previous['profile_sha256'], 'SLO changed')
    require(manifest['frozen_dependencies'] == previous['frozen_dependencies'], 'V1 changed')
    base = read(static_reference/'seed202-static3/backend/manifest.json')
    traces = {}
    for seed in (307, 308):
        trace = read(folder/f'trace-{seed}.json')
        require(trace == make_trace(seed), 'frozen trace mismatch')
        expected = hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest()
        require(read(folder/f'trace-{seed}-hash.json')['sha256'] == expected, 'trace hash mismatch')
        traces[seed] = trace
    reconstructed, case_names = [], set()
    for record in report['completed']:
        step = next_step(reconstructed)
        require(step['kind'] == 'run', 'extra run after terminal decision')
        seed, rate = step['seed'], step['rate']
        require((record['seed'], record['rate']) == (seed, rate), 'off-plan case')
        name = f'seed{seed}-static{rate}'
        case_names.add(name)
        case = folder/name
        meta = read(case/'fixed/run_metadata.json')
        require(meta['config'] == {**config, 'seed': seed, 'fixed_rate': rate}, 'case config changed')
        require(meta['profile'] == manifest['profile'], 'case SLO changed')
        backend = read(case/'backend/manifest.json')
        require(backend['sources'] == manifest['source_files'], 'source changed during batch')
        require(normalized_command(backend['command']) == normalized_command(base['command']), 'engine flags changed')
        require(backend['model_config_sha256'] == base['model_config_sha256'], 'model config changed')
        require(read(case/'backend/cleanup.json')['stopped'], 'owned cleanup failed')
        require(read(case/'backend/warmup.json') == [dict(token=True, done=True, status=200)]*4, 'warmup changed')
        result = analyze_case(case, traces[seed], seed, rate)
        require(result == read(case/'analysis.json') == record, 'analysis reconstruction mismatch')
        reconstructed.append(result)
        require(read(folder/f'checkpoint-{len(reconstructed):02d}.json') ==
                dict(completed=reconstructed, next_step=next_step(reconstructed)), 'checkpoint mismatch')
    require({p.name for p in folder.iterdir() if p.is_dir()} == case_names, 'unreported case directory')
    require({p.name for p in folder.glob('checkpoint-*.json')} ==
            {f'checkpoint-{i:02d}.json' for i in range(1, len(reconstructed)+1)}, 'checkpoint set mismatch')
    selected = next_step(reconstructed)
    require(selected['kind'] == 'stop' and selected == report['selection'], 'missing/changed terminal selection')
    return dict(status='passed', source_hashes_verified=len(manifest['source_files']),
                cases_executed=len(reconstructed), maximum_cases=6,
                offered_records=sum(c['accounting_requests'] for c in reconstructed),
                completed_slo_violations=sum(c['completed_slo_violations'] for c in reconstructed),
                selection=selected, cases=reconstructed,
                caveat='Sequential development calibration only; not held-out or recovery validation.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--static-reference', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.folder, args.snapshot, args.static_reference)
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
