"""Independent standard-library recheck of saved cancellation evidence."""
import argparse
import json
import math
from pathlib import Path
import re


def require(value, message):
    if not value:
        raise ValueError(message)


def metric_file(path):
    output = {}
    names = {'vllm:num_requests_running': 'running', 'vllm:num_requests_waiting': 'waiting',
             'vllm:generation_tokens_total': 'tokens'}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        match = re.match(r'([^\s{]+)(\{[^}]*\})?\s+(\S+)', line)
        if not match:
            continue
        name, labels, value = match.groups()
        key = names.get(name)
        if name == 'vllm:request_success_total':
            for reason in ('abort', 'length'):
                if f'finished_reason="{reason}"' in (labels or ''):
                    key = reason
        if key:
            number = float(value)
            require(math.isfinite(number) and number >= 0, 'invalid counter')
            output[key] = output.get(key, 0)+number
    require(set(output) == {'running', 'waiting', 'tokens', 'abort', 'length'}, 'missing metrics')
    return output


def raw_last(folder, label):
    paths = sorted(folder.glob(f'metrics-*-{label}.txt'))
    require(paths, f'no raw scrape for {label}')
    return metric_file(paths[-1])


def exact_abort_events(text, tag):
    require(isinstance(tag, str) and bool(tag), 'missing request tag')
    pattern = re.compile(r'Request cmpl-' + re.escape(tag) + r'-0 aborted\.')
    return [line for line in text.splitlines() if pattern.search(line)]


def audit(folder):
    control = json.loads((folder/'full-length-control.json').read_text())
    require(control['result']['success'] and control['result']['e2el_ms'] > 3000, 'invalid full-length control')
    before, after = raw_last(folder, 'control-before'), raw_last(folder, 'control-after')
    require(after['length']-before['length'] == 1 and after['tokens']-before['tokens'] == 2048,
            'full-length counter mismatch')
    summary = []
    for attempt in (1, 2):
        case = json.loads((folder/f'case-{attempt}.json').read_text())
        before, after = raw_last(folder, f'{attempt}-before'), raw_last(folder, f'{attempt}-after')
        require(before == case['before']['metrics'] and after == case['after']['metrics'], 'raw/JSON mismatch')
        require(before['running'] == before['waiting'] == after['running'] == after['waiting'] == 0, 'not isolated/idle')
        abort_delta = after['abort']-before['abort']
        require(after['length'] == before['length'], 'request reached normal length completion')
        if case.get('protocol') == 'tagged-request-v2':
            events = exact_abort_events((folder/'backend.log').read_text(encoding='utf-8', errors='replace'), case['request_tag'])
            require(len(events) == 1 and events == case['tagged_abort_lines'], 'tagged cancellation evidence mismatch')
            require(case['checks']['tagged_abort_event'], 'tagged cancellation check failed')
            require(case['abort_counter_check'] == (abort_delta == 1), 'counter diagnostic mismatch')
        else:
            require(case['checks']['abort_increment'] == (abort_delta == 1), 'abort verdict disagrees with raw counter')
        tokens = after['tokens']-before['tokens']
        require(0 < tokens < 2048, 'full token budget exhausted')
        require(any(metric_file(p)['running'] >= 1 for p in folder.glob(f'metrics-*-{attempt}-during.txt')), 'running never seen')
        result = case['client_result']
        require(result['error'] == 'TimeoutError' and result['outcome'] == 'timeout' and result['ttft_ms'] is not None,
                'client timeout not established')
        suffix = []
        for sample in reversed(case['post']):
            m = sample['metrics']
            if m['running'] or m['waiting'] or m['tokens'] != after['tokens']:
                break
            suffix.append(sample)
        require(len(suffix) >= 2 and suffix[0]['at']-suffix[-1]['at'] >= 2, 'no two-second token plateau')
        require(case['after']['at']-case['client_finished_at'] < 10, 'cancellation observation deadline exceeded')
        actions = [c for c in case['controls'] if c['applied']]
        require(len(actions) == 1 and actions[0]['decision']['reason'] == 'request_timeout'
                and math.isclose(actions[0]['decision']['rate'], 2.1), 'timeout decrease mismatch')
        require(case['checks']['gate_released'] and case['checks']['healthy'] and case['recovery']['success'], 'recovery failed')
        require(case['passed'] == all(case['checks'].values()), 'case verdict inconsistent')
        summary.append(dict(attempt=attempt, protocol_passed=case['passed'], generated_tokens=tokens, abort_delta=abort_delta,
                            observed_idle_after_client_s=case['first_idle_observed_after_client_s'],
                            plateau_confirmed_after_client_s=case['plateau_confirmed_after_client_s']))
    require(json.loads((folder/'cleanup.json').read_text())['stopped'], 'process cleanup incomplete')
    expected_status = 'passed' if all(c['protocol_passed'] for c in summary) else 'failed'
    require(json.loads((folder/'report.json').read_text())['status'] == expected_status, 'driver verdict inconsistent')
    return dict(evidence_consistency='passed', original_protocol_status=expected_status,
                full_length_duration_ms=control['result']['e2el_ms'], cases=summary,
                limitation='original protocol verdict preserved; metric sampling is not exact cancellation latency')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.folder)
    if args.output:
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
