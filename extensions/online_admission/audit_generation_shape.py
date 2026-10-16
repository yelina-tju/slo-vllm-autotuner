"""Supplementary raw-metric diagnostic; does not alter preregistered verdicts."""
import argparse
import json
import math
from pathlib import Path
import re


def generation_counts(raw):
    names = {'vllm:request_generation_tokens_count': 'count',
             'vllm:request_generation_tokens_sum': 'tokens'}
    found = {}
    for line in raw.splitlines():
        match = re.fullmatch(r'([^\s{]+)(?:\{.*\})?\s+([^\s]+)(?:\s+\S+)?', line)
        if match and match[1] in names:
            value = float(match[2])
            if not math.isfinite(value) or value < 0:
                raise ValueError('invalid generation metric')
            key = names[match[1]]
            found[key] = found.get(key, 0)+value
    if set(found) != {'count', 'tokens'}:
        raise ValueError('missing generation histogram count/sum')
    return found


def diagnostic(folder):
    result = []
    for path in sorted(folder.glob('seed*-static*/queue.jsonl')):
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        counts = [generation_counts(row['raw']) for row in rows]
        summary = json.loads((path.parent/'fixed/summary.json').read_text())
        expected = summary['successes']+4  # same64-token warmups, reported separately
        result.append(dict(case=path.parent.name, samples=len(counts),
            cumulative_counts_monotone=all(b['count'] >= a['count'] for a, b in zip(counts, counts[1:])),
            all_samples_aggregate_mean64=bool(counts) and all(
                math.isclose(c['tokens'], 64*c['count'], abs_tol=1e-6) for c in counts),
            final_observed_completions=counts[-1]['count'] if counts else None,
            expected_completions_including_warmup=expected,
            caveat='aggregate histogram only; sampled counters can lag the final completion'))
    return dict(cases=result, scope='supplementary diagnostic, not a new inclusion criterion or per-request token proof')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = diagnostic(args.folder)
    if args.output:
        with args.output.open('x', encoding='utf-8') as output:
            json.dump(result, output, indent=2)
    print(json.dumps(result, indent=2))
