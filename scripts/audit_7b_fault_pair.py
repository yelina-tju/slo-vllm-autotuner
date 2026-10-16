"""Read-only request-level audit of a completed independent 7B fault pair."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def audit(directory):
    manifest = json.loads((directory / 'trace_manifest.json').read_text())
    rows = []
    for mode in manifest['config']['modes']:
        folder = directory / mode['name']
        result = json.loads((folder / 'result.json').read_text())
        injection = json.loads((folder / 'fault_proxy.json').read_text())
        expected = {r['request_id']: (r['payload_sha256'], r['scheduled_offset_s']) for r in manifest['trace']}
        actual = {r['request_id']: (r['payload_sha256'], r['scheduled_offset_s']) for r in result['requests']}
        assert expected == actual and len(result['requests']) == len(expected)
        assert result['run_key'] == manifest['run_key'] and not result['control_errors']
        by_payload = {r['payload_sha256']: r for r in result['requests']}
        assert len(by_payload) == len(result['requests'])
        faults = [r for r in injection['records'] if r['injected']]
        short = next(c for c in manifest['classes'] if c['name'] == 'interactive_short')
        exposed = []
        for fault in faults:
            r = by_payload[fault['payload_sha256']]
            if r['error'] or r['ttft_ms'] is None or r['ttft_ms'] > short['ttft_slo_ms'] or r['e2el_ms'] > short['e2el_slo_ms']:
                exposed.append(r['request_id'])
        rollbacks = [e for e in result['executions'] if e['action'] == 'rollback' and e['status'] == 'applied'
                     and injection['armed_s'] is not None and e['started_at_s'] >= injection['armed_s']]
        restart_rollbacks = [e for e in rollbacks if e['requires_server_restart']]
        terminal_ok = not result['final_admission']['paused']
        if injection['armed_s'] is None:
            status = 'not_reached'
        elif injection['enabled']:
            status = 'passed' if rollbacks and faults and terminal_ok and result['final_admission']['rate_limit_rps'] == 3 and not any(r.get('error') for r in injection['records']) else 'failed'
        else:
            status = 'passed' if result['final_state']['admission_limit_rps'] == 12 and terminal_ok and result['restart_count'] == 0 else 'failed'
        rows.append({'mode': mode['name'], 'status': status,
            'injected_requests': len(faults), 'slo_violating_injected_ids': exposed,
            'exposure_count': len(exposed), 'goodput_rps': result['summary']['request_goodput'],
            'status_counts': result['summary']['status_counts'],
            'rollback_delay_s': None if not rollbacks else rollbacks[0]['completed_at_s'] - injection['armed_s'],
            'rollback_final_policy': None if not rollbacks else rollbacks[0]['active_policy'],
            'rollback_chain': [{
                'from_policy': e['from_policy'],
                'target_policy': e['target_policy'],
                'active_policy': e['active_policy'],
                'requires_server_restart': e['requires_server_restart'],
                'delay_from_fault_s': e['completed_at_s'] - injection['armed_s'],
            } for e in rollbacks],
            'cascaded_to_server_restart': bool(restart_rollbacks),
            'final_active_policy': result['final_state']['active_policy'],
            'restart_count': result['restart_count']})
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory), indent=2))
