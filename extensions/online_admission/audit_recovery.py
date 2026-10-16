"""Read-only provenance and request-level reconstruction of recovery evidence."""
import argparse
import hashlib
import json
from pathlib import Path
from audit_alignment_pairs import require
from audit_static_endpoints import normalized_command
from recovery_plan import CONFIG, validate, plan, make_trace, case_config
from recovery_analysis import analyze_case, verdict


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(folder, snapshot, calibration, allow_partial=False):
    manifest, report = read(folder/'manifest.json'), read(folder/'report.json')
    validate(manifest['config'])
    partial = report['status'] != 'passed'
    require(not partial or allow_partial, 'batch failed or incomplete')
    require(set(manifest['source_files']) == {p.name for p in snapshot.glob('*.py')}, 'source file set mismatch')
    for name, expected in manifest['source_files'].items():
        require(Path(name).name == name and sha(snapshot/name) == expected, f'source hash mismatch: {name}')
    prior = read(calibration/'manifest.json')
    require(manifest['profile'] == prior['profile'] and manifest['profile_sha256'] == prior['profile_sha256'], 'SLO changed')
    require(manifest['frozen_dependencies'] == prior['frozen_dependencies'], 'V1 changed')
    require(manifest['calibration_report_sha256'] == sha(calibration/'report.json'), 'calibration changed')
    selected = read(calibration/'report.json')['selection']
    require(selected['status'] == 'candidate_found' and (selected['low_rate'], selected['high_rate']) == (24, 48), 'wrong anchors')
    baseline = read(calibration/'seed307-static24/backend/manifest.json')
    traces = {}
    for seed in (309, 310):
        trace = read(folder/f'trace-{seed}.json')
        require(trace == make_trace(seed), 'trace mismatch')
        expected = hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest()
        require(read(folder/f'trace-{seed}-hash.json')['sha256'] == expected, 'trace hash mismatch')
        traces[seed] = trace
    records = []
    cases = plan(CONFIG)
    if partial:
        require(report['status'] == 'failed' and 0 < len(report['completed']) < len(cases), 'invalid partial batch')
        require(report.get('error') == "OSError(98, 'Address already in use')", 'unreviewed partial failure')
        pending = cases[len(report['completed'])]
        pending_name = f'seed{pending["seed"]}-{pending["arm"]}'
        pending_folder = folder/pending_name
        require(pending_folder.is_dir() and not list(pending_folder.iterdir()), 'failed case was not prelaunch-empty')
    else:
        require(len(report['completed']) == len(cases), 'wrong case count')
    for item, recorded in zip(cases, report['completed']):
        seed, arm = item['seed'], item['arm']
        require((recorded['seed'], recorded['arm']) == (seed, arm), 'case order mismatch')
        case = folder/f'seed{seed}-{arm}'
        config, mode = case_config(CONFIG, seed, arm)
        meta = read(case/mode/'run_metadata.json')
        require(meta['config'] == config and meta['profile'] == manifest['profile'], 'case config/SLO changed')
        backend = read(case/'backend/manifest.json')
        require(backend['sources'] == manifest['source_files'], 'source changed mid-run')
        require(normalized_command(backend['command']) == normalized_command(baseline['command']), 'engine flags changed')
        require(backend['model_config_sha256'] == baseline['model_config_sha256'], 'model changed')
        require(read(case/'backend/cleanup.json')['stopped'], 'cleanup failed')
        require(read(case/'backend/warmup.json') == [dict(token=True, done=True, status=200)]*4, 'warmup mismatch')
        result = analyze_case(case, traces[seed], seed, arm)
        require(result == recorded == read(case/'analysis.json'), 'analysis reconstruction mismatch')
        records.append(result)
        require(read(folder/f'checkpoint-{len(records):02d}.json') == dict(completed=records), 'checkpoint mismatch')
    expected_directories = {f'seed{c["seed"]}-{c["arm"]}' for c in cases[:len(records)]}
    if partial:
        expected_directories.add(pending_name)
    require({p.name for p in folder.iterdir() if p.is_dir()} == expected_directories, 'unreported case directory')
    require({p.name for p in folder.glob('checkpoint-*.json')} ==
            {f'checkpoint-{i:02d}.json' for i in range(1, len(records)+1)}, 'checkpoint set mismatch')
    reconstructed = (dict(status='not_evaluated_incomplete_batch', remaining_cases=cases[len(records):])
                     if partial else verdict(records))
    if partial:
        require('verdict' not in report, 'partial batch must not claim a final verdict')
    else:
        require(reconstructed == report['verdict'], 'verdict mismatch')
    return dict(status='completed_prefix_verified' if partial else 'passed',
                batch_status=report['status'], source_hashes_verified=len(manifest['source_files']),
                offered_records=sum(c['accounting_requests'] for c in records),
                verdict=reconstructed, cases=records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--calibration', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--allow-partial', action='store_true', help='audit only a reviewed prelaunch-port-failure prefix')
    args = parser.parse_args()
    result = audit(args.folder, args.snapshot, args.calibration, args.allow_partial)
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, indent=2))
