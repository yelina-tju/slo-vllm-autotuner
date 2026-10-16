# Development recovery: independently verified

2026-09-21. The earlier transfer-approval blocker is resolved. No completed GPU
case was repeated. Both preserved prefix cases and all four continuation cases
were reconstructed locally from raw evidence and their executed snapshots.

## Evidence

- Local linked audit: `../work/recovery-continuation-sep21-audit.json` relative
  to the repository root (the work directory is beside the repository).
- Audit status: `linked_evidence_verified`; 2 preserved + 4 new cases;
  71,364 offered request records; verdict `recovery_replicated`.
- Continuation archive SHA256:
  `3c852e87dfd3db788ca31bd23a236600c145830ae63270ade82830d174cd588c`.
- 168 archive members validated before extraction; 65 continuation Python source
  hashes checked, together with the earlier executed prefix snapshot.
- Supplementary timing/counter diagnostics:
  `work/recovery-continuation-sep21-diagnostics.json` beside the repository.

## Whole-trace results (240 seconds, not only recovered tail)

| Seed | Arm | Scheduled compliant requests/s | Successful responses | Service SLO violations | Rejections |
|---|---|---:|---:|---:|---:|
| 309 | Fixed24 | 17.9458 | 4308 | 1 | 7481 |
| 309 | Fixed48 | 4.1417 | 8153 | 7118 | 3636 |
| 309 | Adaptive | 21.8875 | 6143 | 880 | 5646 |
| 310 | Fixed24 | 18.1792 | 4363 | 0 | 7636 |
| 310 | Fixed48 | 6.3750 | 8208 | 6581 | 3791 |
| 310 | Adaptive | 22.3125 | 6199 | 834 | 5800 |

Adaptive gains over Fixed24 are 3.9417 and 4.1333 compliant requests/s, but
incurs 879 and 834 additional service violations. This is a throughput/safety
tradeoff, NOT Pareto dominance. Fixed24 is a conservative anchor, not an oracle.

Both adaptive runs decrease admission 48 -> 33.6 once, without restarting the
backend during traffic. Actions acknowledge near t=60.43s; settling ends near
t=80.43s; recovery confirms near t=120.84/120.86s, before high offered load
ends at t=200s. Two consecutive fresh healthy windows and all later eligible
windows satisfy the frozen gate. Roughly 80.84s from high-load onset to confirmed
recovery includes observation, settling and confirmation, not merely actuation.
The approximately 5ms acknowledgement gap is NOT a measured overhead ablation.

## Provenance and limits

The initial batch failed before launching its third case because the old private
port probe rejected a bind. Its failed report and two valid cases remain intact.
The continuation changed the port preflight and reused those cases explicitly;
it did not silently replace the failed batch. Raw accounting, telemetry, warmup,
cleanup, source/configuration hashes and checkpoints were independently checked.

These are two development traces on one model/shape/load distribution. No broad
generalization, statistical significance, optimality or production reliability is
established. V1 and career materials remain unchanged during this extension.

## Next gate

Run six same-distribution held-out cases on seeds401/402 only AFTER the dedicated
runner/auditor is tested and protocol/source/traces frozen. Preserve the existing
controller and measurement predicates. No held-out GPU results exist yet.
