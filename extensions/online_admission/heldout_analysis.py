"""Pre-outcome paired verdict for the two registered held-out seeds.

Request/window reconstruction remains recovery_analysis.analyze_case unchanged.
Execution success is deliberately separate from this scientific verdict.
"""
from audit_alignment_pairs import require


def verdict(cases):
    expected = {(s, a) for s in (401, 402) for a in ('low', 'high', 'adaptive')}
    require(len(cases) == 6 and {(c['seed'], c['arm']) for c in cases} == expected,
            'incomplete or unregistered held-out batch')
    pairs = []
    for seed in (401, 402):
        arms = {c['arm']: c for c in cases if c['seed'] == seed}
        low, high, adaptive = (arms[k] for k in ('low', 'high', 'adaptive'))
        baseline = (all(c['before_healthy'] for c in arms.values())
                    and low['low_anchor_reproduced'] and high['high_anchor_reproduced'])
        pairs.append(dict(seed=seed, baselines_valid=baseline,
                          recovery_pass=baseline and adaptive['recovery']['recovered'],
                          adaptive_goodput=adaptive['goodput'], low_goodput=low['goodput'],
                          high_goodput=high['goodput'],
                          adaptive_minus_low_goodput=adaptive['goodput']-low['goodput'],
                          adaptive_minus_high_goodput=adaptive['goodput']-high['goodput'],
                          adaptive_minus_low_rejections=adaptive['rejections']-low['rejections'],
                          adaptive_minus_low_violations=adaptive['completed_slo_violations']-low['completed_slo_violations'],
                          adaptive_minus_high_violations=adaptive['completed_slo_violations']-high['completed_slo_violations']))
    status = ('inconclusive_baseline' if not all(p['baselines_valid'] for p in pairs) else
              'recovery_replicated' if all(p['recovery_pass'] for p in pairs) else 'recovery_not_replicated')
    return dict(status=status, pairs=pairs,
                caveat='two same-distribution held-out traces; descriptive replication, not broad generalization or Pareto dominance')
