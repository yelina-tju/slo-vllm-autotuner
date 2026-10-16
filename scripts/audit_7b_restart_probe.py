"""Read-only contract audit for completed 7B restart executor probes."""
import argparse
import json
from pathlib import Path


def contains_in_order(actual, expected):
    cursor = 0
    for item in actual:
        if cursor < len(expected) and item == expected[cursor]:
            cursor += 1
    return cursor == len(expected)


def audit(path: Path, expect_failure: bool) -> dict[str, object]:
    report = json.loads(path.read_text())
    execution = report['execution']
    event = report['events'][0]
    common_steps = [
        'admission_paused',
        'in_flight_drained',
        'source_stopped',
        'target_start_command_succeeded',
    ]
    terminal_steps = (
        [
            'target_health_failed',
            'failed_target_stopped',
            'source_restart_command_succeeded',
            'source_health_passed',
            'source_warmup_passed',
            'source_admission_resumed',
        ]
        if expect_failure
        else [
            'target_health_passed',
            'target_warmup_passed',
            'target_admission_resumed',
        ]
    )
    checks = {
        'probe_passed': report['status'] == 'passed',
        'in_flight_observed': report['in_flight_before']['in_flight'] >= 1,
        'paused_request_rejected': report['paused_request_status'] == 503,
        'restart_required': event['requires_server_restart'],
        'drained': execution['drained'],
        'admission_resumed': execution['admission_resumed'],
        'ordered_steps': contains_in_order(execution['steps'], common_steps + terminal_steps),
        'terminal_health_passed': report['terminal_health'][0] is True,
        'post_recovery_completion_passed': report['post_recovery_completion_passed'] is True,
        'cleanup_passed': report['cleanup'][0] is True,
        'one_execution_event': len(report['events']) == 1,
    }
    if expect_failure:
        checks.update({
            'failure_injected': report['target_failure_injected'] is True,
            'failure_recorded': execution['status'] == 'startup_failed_rolled_back',
            'source_restored': execution['active_policy'] == execution['from_policy'],
        })
    else:
        checks.update({
            'failure_not_injected': report['target_failure_injected'] is False,
            'switch_applied': execution['status'] == 'applied',
            'target_active': execution['active_policy'] == execution['target_policy'],
        })
    return {
        'path': str(path),
        'status': 'passed' if all(checks.values()) else 'failed',
        'checks': checks,
        'execution_status': execution['status'],
        'duration_s': event['duration_s'],
        'final_policy': execution['active_policy'],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--success', type=Path, required=True)
    parser.add_argument('--failure', type=Path, required=True)
    args = parser.parse_args()
    results = [audit(args.success, False), audit(args.failure, True)]
    print(json.dumps(results, indent=2))
    raise SystemExit(0 if all(row['status'] == 'passed' for row in results) else 1)
