# Next stage: same-distribution held-out recovery confirmation (CPU preparation)

Execution update: dedicated runner/auditor and frozen protocol are implemented;
prelaunch tests passed and the six-case attempt has launched. No outcome is yet
claimed. See HELDOUT_EXECUTION_STATUS.md. The preparation text below records the
design and gates before launch.

2026-09-21. User requested the next stage after summarizing the recovery work.
No held-out GPU run has started. The transfer blocker is now resolved: the
continuation archive is backed up and all six linked development cases passed
independent local raw-evidence audit. See RECOVERY_RESULTS.md. The historical
interruption remains documented in RECOVERY_CONTINUATION_STATUS.md.

## Question and minimum practical design

With the algorithm/configuration fixed, do the recovery behavior and
safety/throughput tradeoff replicate on two unseen Poisson arrival/prompt traces?
This is SAME model/shape/load distribution, not mixed-workload, second-model,
production reliability or broad generalization validation.

Proposed seeds401/402, never GPU-tested here. Three arms per seed:fixed24,
fixed48,adaptive-from48. Six runs is the smallest proposed design that keeps
both static controls and a second trace; it is not a statistical sample-size or
power claim. Order401 LOW/HIGH/adaptive,402 adaptive/HIGH/LOW. Reversal partially
controls order, but HIGH remains middle; acknowledge that limitation.

All model/shape/SLO,40/160/40s offered6/72/6 phases,20s evidence/settling,
0.7 decrease,0.8 growth margin and other settings are unchanged from development.
Only protocol ID and orders/seeds differ. CPU-generated counts are12,092 and
12,042, both within14,000. No simulated model outcomes were used to choose seeds.
Exactly six fresh-engine cases,240s each:24 minutes of traffic alone, plus
startup/warmup/cleanup. Keep600s per-case and3900s batch limits; no extra seeds,
retries or extension of the load search based on observed results.

## Prerequisites before GPU execution

1. Restore approval availability; download the already-created continuation
   archive without rerunning anything. Check the recorded SHA256 and safely
   extract into a new local directory.
2. Reconstruct the six linked development cases from BOTH snapshots with
   audit_recovery_continuation.py. Require a valid linked audit and replicated
   recovery before launching this proposed confirmation. Preserve any negative
   audit or baseline result; do not merely replace it with the runner console.
3. Review full-trace costs, phase costs and timing diagnostics. Original V1 and
   career claims stay frozen. Never count only the recovered tail.
4. Implement/test a dedicated held-out runner/auditor accepting401/402 while
   preserving the measurement and recovery predicates. Current recovery runner
   and verdict deliberately target309/310; do not silently relabel old results.
5. Freeze/archive final held-out protocol, config, traces and source hashes before
   first launch. Verify GPU/port idle and that output directory does not exist.

## Acceptance and reporting

Reuse the preregistered development criteria without weakening them: healthy
initial windows in all arms, healthy LOW high-phase baseline, at least two HIGH
breached windows, and adaptive recovery confirmed by two consecutive fresh
healthy same-epoch/revision windows after the final high-phase decrease/settling,
ending AND emitted before high offered load ceases at200s. Preserve later
eligible-window failures and require both seeds for replication.

Separate successful execution, valid baselines and recovery confirmation.
Report full240s scheduled and actual-admission-timestamp goodput, service
violations, rejection counts, before/high/after accounting, action timing and
per-seed differences. Outperforming fixed24 is not a prerequisite or promised
result. Fixed24 is a conservative anchor, not a best-static oracle. Higher
goodput with more initial violations is a tradeoff, not Pareto dominance.

Two new seeds give descriptive replication only. No p-value/confidence or
global-optimality claim. Do not retune after seeing held-out results and then
reuse the same traces as "held-out". No second-model/mixed-class GPU work
automatically follows this confirmation.

## What is implemented now

heldout_plan.py is CPU-only: six-case plan, deterministic bounded traces,
configuration checks and prerequisite inspection. It has NO --execute option
and always reports gpu_launch_allowed=false. Even a passing summary requires
raw source/evidence re-audit and a frozen runner. No bypass of blocked transfers.

Historical preparation: six dedicated planning tests plus twelve existing linked-audit/continuation tests
passed locally (18 total,2.210s). At that time preview reported blocked_missing_evidence
for the missing local continuation archive and linked audit. The cloud GPU was
verified idle after development completion; the instance must not be deleted
while the four-case raw evidence remained cloud-only. This evidence is now local.

The separate heldout_analysis.py verdict accepts only seeds401/402, preserves
baseline/recovery gates and explicitly reports additional violations versus LOW.
It does not require throughput superiority to declare recovery replication.
The dedicated GPU runner and independent batch auditor are still required before launch.
