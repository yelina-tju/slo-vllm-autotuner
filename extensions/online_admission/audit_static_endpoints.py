"""Read-only offline audit of the four static endpoint development runs."""
import argparse
import hashlib
import json
from pathlib import Path

from audit_alignment_pairs import audit_batch, audit_mode, require
from run_static_endpoints import plan


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def normalized_command(command):
    result = list(command)
    index = result.index('--port')
    require(index + 1 < len(result), 'missing port value')
    result[index+1] = '<private-port>'
    return result


def audit(folder, reference, snapshot):
    manifest, report = read(folder/'manifest.json'), read(folder/'report.json')
    expected = plan(reference)
    for key, value in expected.items():
        require(manifest[key] == value, f'plan mismatch: {key}')
    require(report['status'] == 'passed', 'batch did not pass')
    require(len(report['completed']) == 4, 'not four completed runs')
    require([r['case'] for r in report['completed']] == expected['cases'], 'changed order or case')
    reference_manifest = read(reference/'batch_manifest.json')
    require(manifest['frozen_dependencies'] == reference_manifest['frozen_dependencies'], 'v1 dependencies changed')
    require(bool(manifest['source_files']), 'missing source hashes')
    for name, value in manifest['source_files'].items():
        require(Path(name).name == name, 'invalid source filename')
        require(hashlib.sha256((snapshot/name).read_bytes()).hexdigest() == value, f'source mismatch: {name}')
    old_results = {p['seed']: p for p in audit_batch(reference)['pairs']}
    cases, pairs = [], []
    for record in report['completed']:
        case = record['case']
        seed, rate = case['seed'], case['fixed_rate']
        directory = folder/f'seed{seed}-static{rate}'
        trace = read(directory/'trace.json')
        require(trace == read(reference/f'seed{seed}/trace.json'), 'changed trace/prompt seeds')
        meta = read(directory/'fixed/run_metadata.json')
        require(meta['config'] == {**manifest['config'], 'seed': seed, 'fixed_rate': rate}, 'changed run configuration')
        require(meta['profile'] == manifest['profile'], 'changed profile/SLO')
        require(meta['duration'] == case['duration'], 'changed duration')
        require(read(directory/'backend/cleanup.json')['stopped'], 'backend cleanup incomplete')
        require(read(directory/'backend/warmup.json') == [dict(token=True, done=True, status=200)]*4, 'warmup mismatch')
        backend = read(directory/'backend/manifest.json')
        old_mode = old_results[seed]['order'][0]
        old_backend = read(reference/f'seed{seed}/{old_mode}-backend/manifest.json')
        require(normalized_command(backend['command']) == normalized_command(old_backend['command']), 'engine command changed')
        require(backend['model_config_sha256'] == old_backend['model_config_sha256'], 'model config changed')
        require(backend['sources'] == manifest['source_files'], 'executed sources changed between runs')
        result = audit_mode(directory/'fixed', trace, 'fixed')
        require(read(directory/'fixed/summary.json') == record['summary'], 'batch summary mismatch')
        require(result == read(directory/'audit.json') == record['audit'], 'saved audit differs from reconstruction')
        cases.append(dict(seed=seed, fixed_rate=rate, duration=case['duration'], **result))
    for seed in (202, 203):
        low = next(c for c in cases if c['seed'] == seed and c['fixed_rate'] == 3)
        high = next(c for c in cases if c['seed'] == seed and c['fixed_rate'] == 6)
        adaptive = old_results[seed]['modes']['adaptive_deadline']
        pairs.append(dict(seed=seed, static3_goodput=low['goodput'], static6_goodput=high['goodput'],
                          historical_adaptive_goodput=adaptive['goodput'],
                          static6_minus_static3=high['goodput']-low['goodput'],
                          historical_adaptive_minus_static6=adaptive['goodput']-high['goodput']))
    return dict(status='passed', cases=cases, comparisons=pairs,
                source_hashes_verified=len(manifest['source_files']),
                caveat='two development seeds; adaptive comparison crosses batches; no best-static or held-out claim')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.folder, args.reference, args.snapshot)
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
