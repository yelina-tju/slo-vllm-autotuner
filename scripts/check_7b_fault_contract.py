"""CPU-only 7B controller contract checks; never connects to a model server.

Uses frozen capacity/SLO evidence, temporary catalog files, synthetic windows
and a logical clock. These checks do not measure HTTP exposure or GPU recovery.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from slo_autotuner.controller import (
    AdaptiveServingController, ClassWindowMetrics, ControllerConfig,
    RequestObservation, RollingWorkloadDetector, load_policy_catalog,
)
from prepare_experiment017_final import build_artifacts


def main():
    paths = [ROOT / p for p in (
        'results/generalization_7b_balanced_capacity_final_policy.json',
        'results/generalization_7b_mixed_capacity_final_policy.json',
        'configs/generalization_7b_workload.json', 'configs/controller.json',
    )]
    balanced, mixed, workload, config = [json.loads(p.read_text(encoding='utf-8')) for p in paths]
    artifacts = build_artifacts(balanced, mixed, workload, config)
    checks = []
    def verify(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    with tempfile.TemporaryDirectory(prefix='7b-fault-contract-') as directory:
        tmp = Path(directory)
        for name, payload in (
            ('policy', artifacts['workload_policy']), ('profiles', artifacts['workload_profiles']),
            ('mixed', mixed), ('controller', artifacts['controller']),
        ):
            (tmp / name).write_text(json.dumps(payload), encoding='utf-8')
        cfg = ControllerConfig.from_json(tmp / 'controller')
        catalog = load_policy_catalog(tmp / 'policy', tmp / 'profiles', tmp / 'mixed', cfg.mixed_profile_name)

        def new(canary=True):
            effective = cfg if canary else replace(cfg, compatible_recovery_canary_admission_limits_rps=())
            detector = RollingWorkloadDetector(effective.rolling_window_seconds, effective.minimum_samples,
                effective.shape_prototypes, effective.profile_distributions)
            c = AdaptiveServingController(effective, catalog, detector)
            c.force_active_policy(catalog.primary_for(cfg.mixed_profile_name).name, 0, 0)
            for i in range(60):
                c.observe_request(RequestObservation(i, 256, 64))
            c.tick(60)
            return c

        def window(c, t, ids, bad=False, missing=False):
            limit = catalog.primary_for('balanced').slo_limits['balanced']
            return c.report_slo_window(t, {} if missing else {
                'balanced': ClassWindowMetrics(6, 0,
                    limit.ttft_ms * (1.2 if bad else .5),
                    limit.e2el_ms * (1.2 if bad else .5),
                    tuple(ids) if bad else (), () if bad else tuple(ids))})

        low = artifacts['low_capacity_rps']
        first, second = artifacts['canary_limits_rps']
        high = artifacts['high_compatible_capacity_rps']
        c = new()
        verify('first_canary_uses_7b_capacity', c.active_policy.admission_limit_rps == first)
        window(c, 70, range(1, 7))
        window(c, 80, range(1, 7))
        verify('reused_success_does_not_promote', c.active_policy.admission_limit_rps == first)
        window(c, 90, range(10, 16))
        verify('fresh_success_promotes_to_second', c.active_policy.admission_limit_rps == second)
        window(c, 100, range(20, 26))
        decision = window(c, 110, range(30, 36))
        verify('healthy_reaches_full_without_restart', c.active_policy.admission_limit_rps == high and not decision.requires_server_restart)

        for canary in (True, False):
            c = new(canary)
            peak = first if canary else high
            window(c, 70, [100], bad=True)
            window(c, 80, [100], bad=True)
            verify(f'reused_violation_does_not_rollback_{canary}', c.active_policy.admission_limit_rps == peak)
            decision = window(c, 90, [101], bad=True)
            verify(f'fresh_fault_returns_to_safe_{canary}', decision.action == 'rollback' and c.active_policy.admission_limit_rps == low and not decision.requires_server_restart)
            c.tick(100)
            verify(f'cooldown_blocks_reexpansion_{canary}', c.active_policy.admission_limit_rps == low)

        c = new()
        window(c, 70, [201]); window(c, 80, [202])
        window(c, 90, [203], bad=True)
        decision = window(c, 100, [204], bad=True)
        verify('second_stage_fault_returns_one_verified_stage', decision.action == 'rollback' and c.active_policy.admission_limit_rps == first)
        c = new()
        window(c, 70, [], missing=True); window(c, 80, [], missing=True)
        verify('missing_metrics_neither_promote_nor_rollback', c.active_policy.admission_limit_rps == first)

    print(json.dumps({
        'status': 'passed', 'checks': checks, 'stages_rps': [low, first, second, high],
        'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'evidence_level': 'CPU controller contract, synthetic SLO windows; no HTTP or GPU claims',
    }, indent=2))


if __name__ == '__main__':
    main()
