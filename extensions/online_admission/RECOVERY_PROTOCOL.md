# Frozen recovery development protocol — dev309–310 v1, 2026-09-21

Prerequisite: audited stage12 LOW24/HIGH48. No more calibration runs.
This protocol freezes the new evaluation before GPU execution. It does not
change controller code/defaults or historical experiments.

## Six cases and bounds

Seed309 order LOW24, HIGH48, adaptive-from48; seed310 order adaptive-from48,
HIGH48, LOW24. Same per-seed Poisson trace and prompt seeds for all three arms.
Reverse order mitigates but does not eliminate order effects; HIGH stays middle.
These are development seeds, not a held-out superiority test.

40s at offered6 RPS ->160s at offered72 RPS ->40s at offered6 RPS; total240s.
High phase [40,200). Exact traces must be generated before launch and contain
<=14,000 requests. This explicit cap increase from10,000 is needed for the longer
observation period, not higher peak offered rate; pending-task cap remains128.
No retries/extra seeds, maximum6 cases,600s/case,3900s/batch plus owned cleanup.
Startup240s, request timeout10s, tick0.25s, dispatch lag<=0.25s. Exclusive output
directory/checkpoints; errors stop remaining cases. No automatic resume.

Frozen Qwen2.5-1.5B FP16/4090D,256input/64output, TTFT100ms/E2E400ms SLO.
Fresh identical engine per case, four warmups. Keep engine flags/model/V1 fixed.
Telemetry once/second: raw metrics,>=200 within-traffic samples,>=230s span,
gap<=3s, scrape<=0.5s. Telemetry/error/accounting failures invalidate the batch,
not evidence of successful overload/recovery. Only owned processes are stopped.

## Adaptive configuration and timing

Deadline-aligned fresh evidence;20s windows and20s settling. Evaluation-only
initial=maximum48, minimum1; multiply0.7 on violation; additive step1;
growth margin0.8, demand fraction0.9,30samples,2healthy confirmations.
Prior default maximum6 is unchanged. This is deliberately adverse initialization,
not recommended ordinary startup. Ideal two-step rate path48->33.6->23.52 is
arithmetic only; it does not guarantee latency monotonicity or recovery.

The160s high phase permits two decreases plus two fresh recovered windows even
with outcome-finalization delays near10s; actual timing is audited, not presumed.

## Acceptance fixed before execution

Successful execution and successful recovery are distinct verdicts.
All three arms must have two healthy initial20s windows. LOW must remain healthy
in all eight high-phase immutable windows AND the whole high phase. HIGH must
have pressure>1 in at least two high-phase windows. Otherwise baseline is
inconclusive; do not claim adaptive benefit or change the workload after the fact.

Healthy = >=30 successful requests, zero backend failures, pressure<=1,
completed violation fraction<=1%. Pressure=max(P99TTFT/100,P99E2E/400).
Recompute immutable accounting windows directly from requests, even across
adaptive revisions; also audit the separate actionable evidence lane.

For adaptive recovery: >=1 acknowledged decrease during [40,200); after its LAST
high-phase decrease and settling deadline, require two consecutive healthy full
20s evidence windows from the same epoch/revision. Both windows must end AND be
emitted by t=200. All later eligible high-phase evidence windows must remain
healthy. Recovery timestamp is when the second qualifying window is emitted,
not its last request or the time low traffic begins. No recovery after t=200 may
be counted toward this criterion. Both development seeds must pass to report
recovery_replicated; otherwise retain recovery_not_replicated/inconclusive_baseline.

## Cost and interpretation

Full240s goodput/violations/rejections include the adverse beginning. Report
before/high/after phase costs by scheduled arrival, with exact partitioning of
all requests. Report acknowledgement/detection/evidence/settling times and actual
admission-timestamp scoring separately. Compare with BOTH matched static arms;
beating staticLOW goodput is not a prerequisite or a promised result. No cherry
picking the recovered tail; no claim of formal stability or global optimality.
Low demand after t=200 can correctly suppress growth. Returning to48 is not the
definition of SLO recovery. No follow-on GPU experiments auto-launch afterward.
