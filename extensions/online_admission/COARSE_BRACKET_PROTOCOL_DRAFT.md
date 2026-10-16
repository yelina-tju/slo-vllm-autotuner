# Proposed bounded coarse search — NOT executed or frozen

Historical draft: superseded for stage12 by COARSE_BRACKET_PROTOCOL.md and
coarse_config.json. The original proposal below is retained for decision history;
its "not implemented" statements describe the pre-stage12 state only.

2026-09-20, after two completed calibration batches with no HIGH cases. This draft
replaces the idea of repeatedly running six-case small expansions. It is not an
automatic permission to launch, and the current runner does not implement it.

## Proposed budget and sequential rule

Retain the same model, shape, SLOs, fresh-engine warmup,120s windows and driver
limits. Use constant offered72 RPS for every case (expected8640 arrivals per120s;
generate and verify exact trace <=10,000 BEFORE launch). Candidate development
seeds307 and308 are proposals only and must be frozen with the implementation.

1. Coarse stage, seed307: start with fixed18 as a fresh within-batch anchor, then
   fixed24,36,48, stopping at the FIRST HIGH case under the existing two-window
   rule. Do not test higher rates after that point.
2. Pair that HIGH with the largest earlier rate classified LOW in this SAME trace.
   AMBIGUOUS rates cannot serve as LOW. If there is no earlier LOW, stop
   inconclusive rather than borrow a lower-rate label from a different batch.
3. If all candidates through48 lack a pair, stop inconclusive. No extra rate or
   seed is added. The cap48 is an experimental budget, not a safe-capacity claim.
4. Only if a candidate pair exists, run seed308 in reverse high/low order using
   identical offered72 and the same frozen classification. Require HIGH and LOW
   to replicate. Failure to replicate ends inconclusive; do not retry for a better
   seed or silently switch to another pair.

At most four coarse runs plus two confirmation runs, six total; fewer when a
bracket is found early or none is found. This is DEVELOPMENT selection with one
replication, not held-out controller performance or a confidence interval claim.

## Required before implementation/execution

- Add explicit sequential-plan unit tests: early HIGH stop, all LOW stop at cap,
  ambiguous exclusion, missing LOW, failed replication, hard error stop, and no
  accidental post-selection extra runs.
- Freeze and archive the exact plan, generated traces and source hashes. Preserve
  partial results if interrupted; do not restart completed stages blindly.
- Reuse current bounds:128 pending tasks,10s request timeout,.25s dispatch lag,
 480s owned-run timeout and3000s batch budget plus cleanup; validate whether these
  remain suitable before freezing. Backend failure/timeout or driver/telemetry
  failure stops the batch and is not automatically interpreted as a HIGH case.
- Keep raw metrics. Sampled waiting0 does not prove no queueing. Do not raise
  limits after a failure merely to make the driver report success.
- No changes to the historical adaptive maximum6 or growth margin0.8. Do not
  execute recovery merely because the coarse stage found a candidate; replication
  and offline audit must finish first.

If this capped search is still inconclusive, review the value of further1.5B
calibration versus an already-supported more demanding model/workload or closing
this extension branch with its negative result. Do not keep expanding indefinitely.
