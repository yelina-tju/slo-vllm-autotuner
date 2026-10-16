"""Offline evidence/provenance audit; never launches backend or changes results."""
import argparse
import hashlib
import json
from pathlib import Path
from audit_alignment_pairs import require
from audit_static_endpoints import normalized_command
from pressure_analysis import validate, protocol_spec, make_trace, analyze_case, select_pair


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(folder, snapshot, static_reference):
    manifest, report = read(folder/'manifest.json'), read(folder/'report.json')
    config = manifest['config']
    validate(config)
    seeds, rates, offered = protocol_spec(config)
    require(report['status'] == 'passed' and len(report['completed']) == 6, 'incomplete calibration batch')
    config_name = 'pressure_config.json' if seeds == (303, 304) else 'pressure_expanded_config.json'
    require(read(snapshot/config_name) == config, 'configuration content mismatch')
    require(sha(snapshot/config_name) == manifest['config_sha256'], 'configuration hash mismatch')
    for name, expected in manifest['source_files'].items():
        require(Path(name).name == name, 'invalid source name')
        require(sha(snapshot/name) == expected, f'source hash mismatch: {name}')
    previous = read(static_reference/'manifest.json')
    require(manifest['profile'] == previous['profile'] and manifest['profile_sha256'] == previous['profile_sha256'], 'SLO changed')
    require(manifest['frozen_dependencies'] == previous['frozen_dependencies'], 'v1 dependency hashes changed')
    base_backend = read(static_reference/'seed202-static3/backend/manifest.json')
    reconstructed, expected_order = [], []
    for order in config['orders']:
        seed = order['seed']
        trace = read(folder/f'trace-{seed}.json')
        require(trace == make_trace(seed, offered), 'trace differs from frozen generator')
        trace_hash = hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest()
        require(read(folder/f'trace-{seed}-hash.json')['sha256'] == trace_hash, 'trace hash mismatch')
        for rate in order['rates']:
            expected_order.append((seed, rate))
            case_folder = folder/f'seed{seed}-static{rate}'
            meta = read(case_folder/'fixed/run_metadata.json')
            require(meta['config'] == {**config, 'seed': seed, 'fixed_rate': rate}, 'run config changed')
            require(meta['profile'] == manifest['profile'], 'run SLO changed')
            backend = read(case_folder/'backend/manifest.json')
            require(backend['sources'] == manifest['source_files'], 'source changed during batch')
            require(normalized_command(backend['command']) == normalized_command(base_backend['command']), 'engine flags changed')
            require(backend['model_config_sha256'] == base_backend['model_config_sha256'], 'model configuration changed')
            require(read(case_folder/'backend/cleanup.json')['stopped'], 'owned cleanup failed')
            require(read(case_folder/'backend/warmup.json') == [dict(token=True, done=True, status=200)]*4, 'warmup differs')
            result = analyze_case(case_folder, trace, seed, rate)
            require(result == read(case_folder/'analysis.json'), 'saved analysis mismatch')
            reconstructed.append(result)
    require([(r['seed'], r['rate']) for r in report['completed']] == expected_order, 'execution order mismatch')
    require(reconstructed == report['completed'], 'batch report reconstruction mismatch')
    selected = select_pair(reconstructed, seeds, rates)
    require(selected == report['selection'], 'selection mismatch')
    return dict(status='passed', source_hashes_verified=len(manifest['source_files']),
                offered_records=sum(c['accounting_requests'] for c in reconstructed),
                completed_slo_violations=sum(c['completed_slo_violations'] for c in reconstructed),
                selection=selected, cases=reconstructed,
                caveat='two development seeds; selection is not held-out performance or a causal queueing proof')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
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
