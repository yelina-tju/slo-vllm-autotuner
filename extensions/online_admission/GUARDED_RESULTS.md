# Guarded recovery: independently verified replication

2026-09-22. Both registered seeds403/404 pass baseline and operational recovery
gates. Both adaptive decreases use a fully high-load arrival window. This is a
bounded single-model result, NOT continuous SLO compliance or broad generalization.

## Evidence and execution

- Six cases executed once; no retries, parameter changes or deleted outcomes.
- Local audit: `../work/guarded-sep22-audit.json` relative to repository root.
  Status guarded_evidence_verified, verdict recovery_replicated.
- 72,822 offered records reconstructed;88 executed Python hashes verified;
  predecessor raw evidence and frozen protocols also checked.
- Archive `../work/guarded-sep22-evidence.tar.gz`,231 safe members, local/remote
  SHA256 `f513ee0660bd3be298bc756a171b9cf5a99f8bb838d16e4baac608c836999206`.
- All owned backends cleaned up. Cloud inspected idle on2026-09-22,0MiB/0%.
  Original V1 regression suite102 tests passed in0.163s. No new GPU work launched.

## Whole260s results, including initialization and guard

| Seed | Arm | Scheduled compliant req/s | Successful responses | Service violations | Rejections |
|---|---|---:|---:|---:|---:|
|403|Fixed24|17.0808|4441|0|7683|
|403|Fixed48|2.7154|8287|7572|3837|
|403|Adaptive|20.3692|6278|978|5846|
|404|Adaptive|20.4769|6312|986|5838|
|404|Fixed48|3.0423|8319|7517|3831|
|404|Fixed24|17.2154|4476|0|7674|

Compared with Fixed24, adaptive gains3.2885 and3.2615 compliant requests/s
(19.2524% and18.9455%), rejects1837 and1836 fewer requests, but adds978 and986
service violations. Compared with Fixed48 it has6594 and6531 fewer violations.
Thus it improves throughput relative to a conservative anchor and limits damage
relative to an aggressive anchor; it does NOT dominate both baselines on every
metric. Fixed24 is not a best-static oracle and these rates are not an optimum.

Scheduled goodput counts responses meeting TTFT100ms and E2E400ms after including
dispatch lag, divided by260s. Service violation counts use measured service
latencies without dispatch lag; these distinct metrics must not be conflated.

## Timing and detection cost

High load starts60s and ends220s. Both adaptive cases:

1. Observe the complete[60,80) high-load arrival cohort.
2. Decrease48 ->33.6 at80.511s /80.529s without backend restart during traffic.
3. End20s settling at100.511s /100.529s.
4. Confirm consecutive fresh healthy windows at140.931s /140.943s, with later
   eligible windows healthy, before offered load declines.

Confirmation takes80.931s /80.943s from load onset, including observation,
finalization, settling and confirmation windows. It is not instant recovery.
The approximately5ms action-acknowledgement gap is not an overhead ablation.

Across the ENTIRE high-load phase, adaptive still has17.21% /17.34% service
violation fractions among successful responses. Full high-phase P99 pressure
exceeds1. Recovery is a later-state property; do not claim the entire episode
met SLO. One404 adaptive guard request also violates and remains included in
the986 total; no transition requests were removed from the denominator.

## What changed versus the inconclusive batch

401/402 remains inconclusive_baseline, with its raw results and verdict unchanged.
The new protocol retains initial validation[0,40), adds normal-load guard[40,60),
then evaluates high load[60,220). It uses different seeds and a260s denominator.
All six clean initial gates pass, as do LOW/HIGH anchors. Full-high-evidence
decreases are directly observed here, unlike the earlier402 boundary response.

This supports the operational recovery claim under the revised frozen protocol.
It does not retroactively validate401/402, isolate the guard's causal effect, or
justify pooling240s and260s results as identically designed repetitions.

## Supplementary diagnostics and limitations

`../work/guarded-sep22-diagnostics.json` records action timing and aggregate token
counters. Sampled generation counts are monotone and aggregate mean output is64;
last sampled totals lag successful responses plus warmups by0–2 in some runs.
These are auxiliary sampled metrics, not per-request token proof or new gates.

Only one Qwen2.5-1.5B model, fixed256/64 shape, one4090D and two new Poisson traces.
No second-model, mixed-length, multi-GPU, statistical-significance or production
reliability claim. Runtime load labels are for analysis only, not controller input.
The whole project may contain earlier7B work; this extension is NOT7B-validated.

## Offline reproduction and closure

From repository root, with Python3.11+:

```sh
python extensions/online_admission/recheck_guarded_evidence.py
```

This verifies five archived evidence bundles and two prelaunch freezes, then
reconstructs the linked audits without network or GPU. It prints a compact
result; optional --output writes exclusively, never overwriting earlier evidence.
Keep the repository AND its sibling work directory. Successful closure recheck:
`../work/guarded-sep22-chain-recheck.json`.

Closure tooling additionally rejects tampered/missing archives and refuses to
interpret240s evidence as260s diagnostics.99 related local regressions passed
in8.135s after these additions; these overlap earlier test sets and are not an
additional99 independent experiments. No executed cloud snapshot was edited.

This bounded recovery-validation stage is complete. No further GPU batch is
required to support the narrow claims above. Broader generalization/overhead
ablation would be new experiments with separate scope, not mandatory reruns.
Shutdown is safe for this completed batch; no instance deletion or career-material
rewrite was performed. Use EXTENSION_EVIDENCE_HANDOFF.md for a concise reviewer map.
