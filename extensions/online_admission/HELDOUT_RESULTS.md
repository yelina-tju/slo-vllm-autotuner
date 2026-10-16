# Held-out recovery: valid evidence, inconclusive baseline

2026-09-21. Six registered cases finished once, with no retries or retuning.
Execution status is passed; independent audit status is heldout_evidence_verified;
the frozen scientific verdict is **inconclusive_baseline** for BOTH pairs.
Do not describe this batch as successful held-out recovery replication.

## Provenance and local backup

Paths below are relative to the repository root; work is its sibling directory.

- Evidence: `../work/heldout-sep21-evidence.tar.gz`.
  SHA256 `b08ae203b7222bb134cb4db77c93c7689c18337741f89997d962c4d9a43cf324`.
- Remote/local hash match;215 safe archive members checked before extraction.
- Extracted evidence: `../work/heldout-sep21-evidence/`.
- Independent audit: `../work/heldout-sep21-audit.json`.
  All72,402 offered records reconstructed,76 executed Python source hashes
  checked, frozen protocol and both historical development snapshots verified.
- Timing diagnostics: `../work/heldout-sep21-diagnostics.json`.
- Boundary diagnostics: `../work/heldout-sep21-boundary-diagnostics.json`.
- Frozen prelaunch protocol SHA256:
  `c776638a7a833b60e96e43c9426f88e3819467cd5438d9a15761b329087f499d`.
- All six owned backends cleaned up. Remote GPU0MiB/0%, no experiment process.
  Post-run original V1 suite102 tests passed in0.160s;24 local held-out tests
  including the new post-hoc diagnostic passed in1.506s. Test sets overlap.

## Whole240s outcomes (descriptive, not a passing validation)

| Seed | Arm | Scheduled compliant req/s | Successful responses | Service violations | Rejections |
|---|---|---:|---:|---:|---:|
|401|Fixed24|17.9750|4314|0|7778|
|401|Fixed48|2.5625|8159|7533|3933|
|401|Adaptive|21.5250|6149|983|5943|
|402|Adaptive|24.2667|5863|39|6179|
|402|Fixed48|2.8875|8158|7449|3884|
|402|Fixed24|17.9708|4313|0|7729|

Adaptive improves observed goodput over LOW by3.55 and6.2958req/s but incurs
983 and39 more service violations. These are paired descriptive differences,
not a proof of generalization, superiority, Pareto dominance or an optimal rate.
Both LOW high-load anchors and both HIGH breach anchors reproduce. The failing
requirement is healthy initial windows in every arm, not raw-data integrity.

## Why the frozen baseline fails

The last initial window is[20,40), defined by actual request arrival. High offered
load begins at40. Requests arriving just before40 can finish after40, while
remaining correctly assigned to their original arrival window.

| Case | Initial[20,40) service violations/successes | P99 pressure | Healthy |
|---|---:|---:|---|
|401 HIGH|2/111|1.075659|false|
|402 adaptive|2/126|1.053551|false|
|402 HIGH|2/126|1.025754|false|

All six violations responsible for these failed windows started at39.886–39.944s
and finished at40.329–40.365s. They breach E2E400ms, not TTFT100ms. Across all
six cases, there were seven initial-phase service violations total (including
one in401 adaptive, which remains below the window failure thresholds); all
seven crossed the load boundary. No initial-phase violating request completed
before40s. This temporal pattern supports a boundary-overlap explanation; it
does not independently prove the scheduler-level cause or rule out all noise.

These are genuine SLO violations, not bad rows. We do NOT drop them, move their
arrival cohorts, relax P99/1% thresholds, or recompute a passing primary verdict.

## Recovery timing is not equivalent across the two cases

401 adaptive: the40–60s high-load evidence window prompts48 ->33.6 at60.425s;
settling ends80.425s; recovery confirms120.838s, before high load ends200s.

402 adaptive: the20–40s boundary-straddling initial cohort prompts the same
decrease at40.612s; settling ends60.612s; recovery confirms101.026s. Its action
occurs after the load step but is based on PRE-step arrivals with POST-step
completions. Therefore its39 violations and faster confirmation must not be sold
as faster detection of a completed high-load evidence window. The frozen
baseline gate correctly prevents that claim, even though the subordinate
recovery predicate is true in both cases.

The controller acts on finalized SLO evidence; this is not shown to be a false
alarm. The identified limitation concerns experiment phase isolation and causal
interpretation. No controller or executed snapshot was changed during diagnosis.

## Next step, without another GPU run yet

Review a new protocol that separates a clean initial-state validation interval
from the load-transition interval. One candidate is to keep two20s validation
windows, then provide a predeclared guard interval exceeding the10s request
timeout before the load step. Guard traffic and transition violations MUST remain
in whole-trace accounting; clean-window eligibility is specified before outcomes.
This would be a different workload protocol and needs new traces, new duration/
window tests and a frozen design, not a relabeling of401/402 or a retroactive pass.

First test the distinction using CPU synthetic boundary cases. Only after review
should any new bounded GPU confirmation be considered. No extra seeds, retries
or new GPU experiment were launched in this review. V1 and career materials stay
unchanged. Shutdown is safe for this completed batch; instance deletion is not
performed automatically.
