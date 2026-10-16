"""Validate paired traces and report phase-bounded recovery outcomes."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = ('asymmetric_controller', 'legacy_symmetric')

def load(directory):
    manifest = json.loads((directory / 'trace_manifest.json').read_text())
    output = {'trace_sha256': manifest['trace_sha256'], 'order': [m['name'] for m in manifest['config']['modes']], 'modes': {}}
    expected = {r['request_id']: (r['payload_sha256'], r['scheduled_offset_s'], r['phase']) for r in manifest['trace']}
    for mode in MODES:
        result = json.loads((directory / mode / 'result.json').read_text())
        actual = {r['request_id']: (r['payload_sha256'], r['scheduled_offset_s'], r['phase']) for r in result['requests']}
        if (result['status'] != 'complete' or result['run_key'] != manifest['run_key']
                or actual != expected or len(result['requests']) != len(expected)
                or result['control_errors']):
            raise ValueError(f'Invalid evidence: {directory}/{mode}')
        phases = []
        for phase in manifest['phases']:
            start, end = phase['start_s'], phase['end_s']
            target = 'mixed_80_20:' if phase['long_fraction'] else 'balanced:'
            transitions = [e for e in result['executions'] if start <= e['started_offset_s'] < end]
            applied = [e for e in transitions if e['status'] == 'applied' and e['target_policy'].startswith(target)]
            summary = result['by_phase'][phase['name']]
            phases.append({'name': phase['name'], 'start_s': start, 'end_s': end,
                'goodput_rps': summary['request_goodput'], 'compliant': summary['slo_compliant'],
                'statuses': summary['status_counts'],
                'recovery_delay_s': min((e['completed_offset_s'] - start for e in applied), default=None),
                'transitions': transitions})
        output['modes'][mode] = {'goodput_rps': result['summary']['request_goodput'],
            'compliant': result['summary']['slo_compliant'], 'statuses': result['summary']['status_counts'],
            'restart_count': result['restart_count'], 'phases': phases}
    output['goodput_delta_rps'] = output['modes'][MODES[0]]['goodput_rps'] - output['modes'][MODES[1]]['goodput_rps']
    return output

if __name__ == '__main__':
    order = load(ROOT / 'results/order_control012')
    original = load(ROOT / 'results/asymmetric_recovery_seed82')
    if order['trace_sha256'] != original['trace_sha256']:
        raise ValueError('Order-control trace does not match original seed82')
    repeated = load(ROOT / 'results/repeated_shift012')
    report = {'order_control': order, 'original_seed82': original, 'repeated_shift': repeated,
        'limitations': ['One reverse-order replication cannot isolate order from time drift.',
            'Two cycles are a repeated-shift pilot, not a long-term reliability claim.',
            'A compatible backend does not guarantee safe increased admission under a misclassified workload.',
            'Recovery latency uses applied completion time bounded to its phase; null means no matching applied transition.']}
    (ROOT / 'results/experiment012_analysis.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k]['goodput_delta_rps'] for k in ('order_control','original_seed82','repeated_shift')}, indent=2))
