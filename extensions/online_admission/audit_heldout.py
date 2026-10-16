"""Independent held-out raw-evidence audit, including linked development gate."""
import argparse
import json
from pathlib import Path
from audit_alignment_pairs import require
from audit_recovery import read, sha
from audit_static_endpoints import normalized_command
from heldout_protocol import CONFIG, arguments, prepare, case_config
from heldout_plan import plan
from heldout_analysis import verdict
from recovery_analysis import analyze_case


def audit_batch(folder, snapshot, args, freeze):
    frozen, traces = prepare(args, snapshot)
    require(read(freeze) == frozen == read(folder/'frozen-protocol.json'), 'frozen protocol mismatch')
    manifest, report = read(folder/'manifest.json'), read(folder/'report.json')
    require(report['status'] == 'passed' and len(report['completed']) == 6, 'incomplete held-out batch')
    require(manifest['config'] == CONFIG and manifest['frozen_protocol'] == frozen, 'manifest protocol mismatch')
    for key in ('source_files', 'profile', 'profile_sha256', 'frozen_dependencies', 'calibration_report_sha256'):
        require(manifest[key] == frozen[key], f'manifest {key} mismatch')
    for seed, trace in traces.items():
        require(read(folder/f'trace-{seed}.json') == trace, 'held-out trace changed')
        require(read(folder/f'trace-{seed}-hash.json') == dict(sha256=frozen['trace_sha256'][str(seed)]), 'trace hash changed')
    records = []
    for item, reported in zip(plan(), report['completed']):
        seed, arm = item['seed'], item['arm']
        require((reported['seed'], reported['arm']) == (seed, arm), 'case order or identity changed')
        case = folder/f'seed{seed}-{arm}'
        config, mode = case_config(CONFIG, seed, arm)
        metadata = read(case/mode/'run_metadata.json')
        require(metadata['config'] == config and metadata['profile'] == frozen['profile'], 'case config/SLO changed')
        backend = read(case/'backend/manifest.json')
        require(backend['sources'] == frozen['source_files'], 'mid-run source changed')
        require(normalized_command(backend['command']) == normalized_command(frozen['backend']['command']), 'backend flags changed')
        require(backend['model_config_sha256'] == frozen['backend']['model_config_sha256'], 'model changed')
        require(read(case/'backend/cleanup.json')['stopped'], 'backend cleanup failed')
        require(read(case/'backend/warmup.json') == [dict(token=True, done=True, status=200)]*4, 'warmup mismatch')
        result = analyze_case(case, traces[seed], seed, arm)
        require(result == reported == read(case/'analysis.json'), 'raw analysis mismatch')
        records.append(result)
        require(read(folder/f'checkpoint-{len(records):02d}.json') == dict(completed=records), 'checkpoint mismatch')
    require({p.name for p in folder.iterdir() if p.is_dir()} ==
            {f'seed{c["seed"]}-{c["arm"]}' for c in plan()}, 'unexpected case directory')
    require({p.name for p in folder.glob('checkpoint-*.json')} ==
            {f'checkpoint-{i:02d}.json' for i in range(1, 7)}, 'unexpected checkpoint set')
    selected = verdict(records)
    require(selected == report['verdict'], 'held-out verdict mismatch')
    return dict(status='heldout_evidence_verified', cases=records, verdict=selected,
                offered_records=sum(c['accounting_requests'] for c in records),
                source_hashes_verified=len(frozen['source_files']), freeze_sha256=sha(freeze))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    arguments(parser)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit_batch(args.folder, args.snapshot, args, args.freeze)
    if args.output:
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, indent=2))
