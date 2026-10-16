# Online admission extension — bounded recovery validation completed

This directory is an independent v2 prototype. It does not change the frozen
v1 controller, experiments or release archive. The 2026-09-22 closeout records
extension evidence separately from V1.
Current state: guarded six-case raw audit passed, evidence is local, no pending
GPU task. See GUARDED_RESULTS.md. The dated entries below are historical;
earlier pending/no-launch statements are not current blockers.

## Implemented

- Bounded additive-increase/multiplicative-decrease feedback using class-specific
  normalized P99 TTFT and end-to-end latency.
- Minimum evidence, demand gate, deadband, consecutive healthy confirmations,
  settling time, and applied-configuration revisions.
- Nonoverlapping windows; gaps reset healthy confirmation. Event and cohort
  adapters enforce unique request attribution and unmixed revisions.
- Explicit proposal/acknowledgement: failed actuation does not change applied
  rate or revision; pending actuation prevents another proposal.
- Ordered start/end event contract with unique IDs, per-class nearest-rank P99,
  rejected requests included in offered demand but excluded from backend failures,
  revision mixing detection, pending counts and oldest-pending age.
- Opt-in HotAdmissionGate: paused updates fail closed, elapsed tokens accrue at
  the old rate, new capacity never gifts tokens, and application shares the
  existing lifecycle executor lock. No v1 source edits.
- Arrival-cohort finalization: later requests no longer block earlier groups;
  each admitted request finishes or expires once. Late completions cannot erase
  timeouts. A bounded-run cap limits retained request IDs.
- Opt-in StreamingPilot client with real HTTP/SSE parsing, client timeout and
  cancellation cleanup, atomic admission revision attribution, serialized ticks.
- Bounded open-loop Linux GPU runner with frozen trace, SLO provenance, source
  hashes, exclusive output directories, request/control logs and owned-process cleanup.
- First real 1.5B smoke completed; independent local accounting audit passed.
- Post-smoke drain-only actuation deadline protection (CPU verified, not GPU rerun).
- A deterministic scripted CPU demonstration and 35 passing unit/integration tests.
- Stage 5: fixed-grid overhead quantified (~19.877s in dev201); two actual GPU
  timeout cases preserved as FAILED under their original abort-counter criterion.
  Installed-source diagnosis explains why that counter may omit this cancel path.
  See FINDINGS_2026-09-14.md. Latest checks: 40 extension tests plus 2 independent
  offline-audit tests; 102 frozen-v1 regressions.
- Stage 6: new tagged-request cancellation protocol passed 2/2 real GPU cases;
  original counter-v1 failure preserved. Added process-level CPU/PSS sampling.
  See TAGGED_CANCEL_AND_RESOURCES.md. Pre-GPU suite: 45 tests; local audit: 3 tests.
- Stage 7: optional deadline-anchored evidence with independent all-request
  accounting; 53 extension tests and 102 v1 regressions passed. CPU identical-event
  comparison proposes growth 19.875s earlier; GPU comparison followed in stage 8.
  See DEADLINE_COHORTS.md.
- Stage 8: four real-GPU paired development runs completed and independently
  audited (5,108 request records). Anchored second growth was 19.554–19.771s
  earlier; each pair gained 31 compliant requests, no observed backend failures
  or SLO violations. Aggregate descriptive goodput +6.5195%, NOT a held-out claim.
  56 frozen extension tests, 6 additional local audit tests and 102 v1 regressions
  passed; CPU stress conserved 25,000 requests across 100 scenarios. Exact source
  and results backed up locally. See ALIGNMENT_PAIRS_RESULTS.md.
- Stage 9 preparation (2026-09-15): fixed admission rate is now independent of
  adaptive initial rate. Static controls are audited for no decisions, no rate
  changes and revision0. 64 CPU/HTTP tests passed in the isolated cloud v11
  snapshot; four further stdlib planning tests passed locally. Read-only planning
  audited the existing stage-8 evidence and selected four static3/static6 runs
  with exact trace hashes and reversed order. No stage-9 GPU run launched yet.
  See STATIC_ENDPOINTS_PROTOCOL.md and STATIC_ENDPOINTS_PREPARATION.md.
- Stage 9 GPU completed: four static endpoint runs, 5,108 offered requests,
  zero observed backend failures/SLO violations, no static actuation. Static3
  compliant totals 750; static6 totals 1441. Historical anchored adaptive totals 1013
  are intermediate (cross-batch comparison only). Static6 E2E P99 of 364–377ms is near
  the 400ms SLO; the next gate is bounded pressure calibration, not a large blind
  rate increase. Full audit, 33 source hashes and local archive verified. See
  STATIC_ENDPOINTS_RESULTS.md; five new offline tests passed.
- Stage 10 (2026-09-19): six bounded pressure-calibration runs at fixed3/6/9
  completed and audited,13,083 offered records,4,036 compliant admissions,
  zero observed SLO violations/backend failures. All36 windows remained within
  SLO; pressure-bracket selection is INCONCLUSIVE, not a recovery-test pass.
  At9 all12 windows entered the0.8–1.0 growth deadband; sampled waiting remained
  zero.81 prelaunch extension tests,7 further local evidence tests and102 v1
  regressions passed.41 executed source hashes and local backup verified.
  See PRESSURE_CALIBRATION_RESULTS.md.
- Stage11 (2026-09-20): bounded6/12/18 expansion completed and audited.26,067
  offered records,8,630 compliant admissions, zero observed SLO violations; all
  six cases LOW, bracket still INCONCLUSIVE.18 RPS P99 E2E about347ms.92 prelaunch
  extension tests and102 v1 regressions passed;44 source hashes and local backup
  verified. Next method should be capped coarse search plus selective replication,
  not another six-case small expansion. See PRESSURE_EXPANSION_RESULTS.md.
- Stage12 completed (2026-09-20): bounded sequential18/24/36/48 search selected
  LOW24/HIGH48, replicated across development seeds307/308.36 was AMBIGUOUS
  (one breached window) and not an eligible LOW. Six runs,51,962 offered records,
  11,241 SLO violations but zero backend failures.106 prelaunch cloud tests,
  102 frozen V1 regressions and45 selected local audit tests passed (overlapping
  test sets).49 executed source hashes, checkpoints and local backup verified.
  No recovery GPU run yet; see COARSE_BRACKET_RESULTS.md.
- Stage13 interrupted (2026-09-21): after126 prelaunch tests, seed309 LOW24/HIGH48
  completed and passed independent prefix audit (23,578 records;56 source hashes).
  Adaptive startup failed at the port preflight BEFORE creating any backend.
  Batch retained as FAILED, recovery NOT EVALUATED; four cases remain. GPU idle.
  An isolated CPU reproduction demonstrates a TIME_WAIT false positive in the
  old probe; local repair preserves rejection of active listeners. The failure's
  transient socket state was not captured, so this is not definitive attribution.
  The isolated repaired v16-review snapshot passed145 CPU/HTTP tests; no GPU
  continuation was launched. Original V1 also passed102 regressions.
  See RECOVERY_ATTEMPT1_RESULTS.md. Do not rerun the two completed controls.
- Stage13 continuation executed (2026-09-21): all four remaining cases finished;
  runner analyses report both adaptive recoveries at about120.85s, before high
  traffic ends at200s.150 prelaunch tests and102 post-run V1 regressions passed.
  Final linked audit/local backup now VERIFIED: all six cases,71,364 offered
  records and both executed snapshots reconstructed locally after transfer
  approval recovered. Both development seeds pass the recovery gate. Higher
  goodput than LOW comes with more initial violations, not Pareto dominance.
  See RECOVERY_RESULTS.md; the original failed attempt remains preserved.
- Next stage CPU preparation: held-out401/402 proposal, six bounded cases;
  plan/trace/prerequisite tools tested, no GPU launch. See HELDOUT_RECOVERY_PLAN.md.
  Update: dedicated runner/auditor implemented;179 cloud CPU/HTTP tests passed.
  Frozen six-case attempt1 completed and locally audited:72,402 requests,76 source
  hashes. Scientific verdict inconclusive_baseline on both pairs: requests crossing
  the load-step boundary violate initial-window SLOs. No rerun or threshold change.
  See HELDOUT_RESULTS.md for full results and the CPU-first next protocol review.
  Phase-isolation proposal now has a20s guard, lossless whole260s accounting,
  observed initial-finalization checks and evidence/action attribution.32 local
  tests pass; no GPU launch. See GUARDED_RECOVERY_PLAN.md for remaining integration gates.
  Integration update: dedicated260s runner and independent audit now implemented,
  96 local tests pass, predecessor raw evidence re-audited, local protocol frozen.
  Linux CPU/HTTP preflight and GPU execution remain pending. See GUARDED_INTEGRATION_STATUS.md.
  Execution update:214 Linux CPU/HTTP tests passed; frozen guarded403/404 attempt1
  launched, outcomes pending. See GUARDED_EXECUTION_STATUS.md. Do not rerun.
  Completion2026-09-22: guarded_evidence_verified, recovery_replicated on both
  seeds;72,822 records and88 source hashes checked, raw backup local. About19%
  whole-trace goodput gain over LOW with978/986 additional violations, not blanket
  SLO compliance. See GUARDED_RESULTS.md and EXTENSION_EVIDENCE_HANDOFF.md.

## Reproduce

From the repository root, using the project environment (including aiohttp),
Python 3.11 or later (asyncio.timeout), with src on PYTHONPATH or the package installed:

```sh
python -m unittest discover -s extensions/online_admission -p 'test_*.py' -v
python extensions/online_admission/replay.py
```

The demonstration exercises 3 -> 4 -> 2.8 RPS, a failed proposal to 3.8, then a
successful proposal to 3.8. These are synthetic contract checks, not measured
safe capacities or evidence of performance improvement.

## Closed gates and optional future scope

1. Paired alignment and static endpoint development comparisons are complete.
   After two inconclusive pressure batches, capped coarse calibration established
   a development LOW24/HIGH48 pair. Recovery attempt1 stopped at a prelaunch port
   failure after two valid controls. The reviewed linked four-case continuation
   finished and independently passed the linked raw-evidence audit. Implement,
   test and freeze the dedicated held-out runner/auditor before any new GPU
   work (completed). The held-out batch is now audited but inconclusive due to
   boundary overlap. Phase-isolated403/404 validation has since completed and
   passed, without changing the old verdict. See RECOVERY_RESULTS.md,
   HELDOUT_RESULTS.md and GUARDED_RESULTS.md. No mandatory rerun remains.
2. Tagged cancellation evidence now passes for the tested isolated path; any
   future concurrency/model expansion needs its own scope and acceptance checks.
3. Static LOW24/HIGH48 baselines and registered new-seed guarded recovery are
   complete. Any additional workload/model expansion requires its own design;
   keep backend fixed until lifecycle resynchronization is implemented.

No public gateway replacement is complete. Bounded new-seed guarded recovery
validation is complete; this is not broad workload/model generalization.
The first GPU smoke is documented in PILOT_DEV201.md. Feedback searches for a
bounded operating point; it is not a
formal capacity estimator or an optimality/stability guarantee. Zero-completion
stalls now yield timeout evidence and decrease proposals without requiring 30
failures. Client timeout closes the HTTP context but does not prove backend GPU
work was cancelled. Earlier CPU stages are recorded in
VALIDATION_COHORTS_2026-09-13.md and VALIDATION_2026-09-13.md.
