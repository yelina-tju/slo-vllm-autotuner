"""Read-only linked audit; validates both snapshots without rewriting either batch."""
import argparse
import hashlib
import json
from pathlib import Path
from audit_alignment_pairs import require
from audit_recovery import read, sha
from audit_static_endpoints import normalized_command
from recovery_continuation import prepare
from recovery_plan import CONFIG, case_config
from recovery_analysis import analyze_case, verdict


def audit(folder, snapshot, prefix, prefix_snapshot, calibration):
    context, traces = prepare(prefix, prefix_snapshot, calibration, snapshot)
    manifest, report = read(folder/'manifest.json'), read(folder/'report.json')
    require(report['status'] == 'passed' and len(report['completed']) == 4, 'continuation incomplete')
    require(manifest['config'] == CONFIG and manifest['continuation'] == context['link'], 'continuation link/config changed')
    require(set(manifest['source_files']) == {p.name for p in snapshot.glob('*.py')}, 'source file set mismatch')
    for name, expected in manifest['source_files'].items():
        require(Path(name).name == name and sha(snapshot/name) == expected, 'continuation source changed')
    previous = read(prefix/'manifest.json')
    for key in ('profile', 'profile_sha256', 'frozen_dependencies', 'calibration_report_sha256'):
        require(manifest[key] == previous[key], f'changed {key}')
    base = read(prefix/'seed309-low/backend/manifest.json')
    for seed, trace in traces.items():
        require(read(folder/f'trace-{seed}.json') == trace, 'saved prefix trace not reused')
        require(sha(folder/f'trace-{seed}.json') == context['link']['trace_file_sha256'][str(seed)], 'trace bytes changed')
        expected = hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest()
        require(read(folder/f'trace-{seed}-hash.json')['sha256'] == expected, 'canonical trace hash mismatch')
    records = []
    for item, reported in zip(context['remaining'], report['completed']):
        seed, arm = item['seed'], item['arm']
        require((reported['seed'], reported['arm']) == (seed, arm), 'repeated or reordered case')
        case = folder/f'seed{seed}-{arm}'
        config, mode = case_config(CONFIG, seed, arm)
        meta = read(case/mode/'run_metadata.json')
        require(meta['config'] == config and meta['profile'] == manifest['profile'], 'case config/SLO changed')
        backend = read(case/'backend/manifest.json')
        require(backend['sources'] == manifest['source_files'], 'mid-run source change')
        require(normalized_command(backend['command']) == normalized_command(base['command']), 'engine flags changed')
        require(backend['model_config_sha256'] == base['model_config_sha256'], 'model changed')
        require(read(case/'backend/cleanup.json')['stopped'], 'cleanup failed')
        require(read(case/'backend/warmup.json') == [dict(token=True, done=True, status=200)]*4, 'warmup mismatch')
        result = analyze_case(case, traces[seed], seed, arm)
        require(result == reported == read(case/'analysis.json'), 'analysis mismatch')
        records.append(result)
        require(read(folder/f'checkpoint-{len(records):02d}.json') == dict(completed=records), 'checkpoint mismatch')
    require({p.name for p in folder.iterdir() if p.is_dir()} ==
            {f'seed{c["seed"]}-{c["arm"]}' for c in context['remaining']}, 'unreported/repeated case directory')
    require({p.name for p in folder.glob('checkpoint-*.json')} ==
            {f'checkpoint-{i:02d}.json' for i in range(1, 5)}, 'checkpoint set mismatch')
    combined = context['prefix_cases']+records
    selected = verdict(combined)
    require(selected == report['verdict'], 'linked verdict mismatch')
    return dict(status='linked_evidence_verified', prefix_batch_status='failed_preserved',
                continuation_status='passed', new_cases=4, preserved_cases=2,
                continuation_source_hashes_verified=len(manifest['source_files']),
                offered_records=sum(c['accounting_requests'] for c in combined),
                verdict=selected, cases=combined, link=context['link'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    for key in ('snapshot', 'prefix', 'prefix-snapshot', 'calibration'):
        parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.folder, args.snapshot, args.prefix, args.prefix_snapshot, args.calibration)
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, indent=2))
