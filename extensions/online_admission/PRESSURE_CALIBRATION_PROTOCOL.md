# Stage 10 frozen development protocol — 2026-09-19

Exactly six runs: seed303 rates3,6,9; seed304 rates9,6,3. Fixed admission only,
not adaptive. Each120s, constant Poisson offered18 RPS, balanced256/64 tokens,
unchanged TTFT100ms and E2E400ms. Identical per-seed arrivals/prompts across rates.
Fresh Qwen2.5-1.5B engine on one4090D and four identical warmups for every run.
All engine flags inherited unchanged from the completed static endpoint batch.
No changes to v1, controller thresholds, adaptive maximum6 or running source.

Rationale: anchor at3 and retain6, then one modest step to9. The earlier static6
E2E tail was close to the400ms threshold; do not jump to a large overload. Offered
18 is fixed across rates to avoid confounding the gate setting with the source
distribution. These are new DEVELOPMENT seeds, not held-out final evaluation.

## Instrumentation and validity

Primary request/control logs retain all existing audit requirements: exact trace
membership, unique IDs, no static actuation, no lost/pending requests, dispatch lag
<=.25s, zero backend failures and owned-process cleanup. Client task cap128,
request timeout10s. Backend failure/timeout or driver failure stops the remaining
batch, preserving evidence; it is not retried or silently excluded. SLO violations
from successful requests remain valid outcomes, never grounds to drop a run.

Collect /metrics once per second with a separate asynchronous sampler and2s HTTP
timeout, storing raw response plus monotonic start/end and parsed running/waiting
gauges. Require >=100 successful within-traffic samples, span>=110s, gaps<=3s,
scrapes<=.5s, no malformed/missing metrics. Invalid telemetry stops after cleanup
of the current bounded run; the driver need not stop instantly on sampler failure.
Telemetry overhead is shared across all arms but not separately measured. Sampled
queue zeros do not prove no short-lived queues. Reconstruct client in-flight peak
independently from request timestamps; it is not identical to backend running count.

## Predeclared selection, not post-hoc threshold tuning

Six full20s windows per run, >=30 successful outcomes per window, zero backend
failures. Window pressure=max(P99TTFT/100ms,P99E2E/400ms).

- LOW: all six pressures<=1, whole-run pressure<=1 and individual completed-request
  SLO violation fraction<=1%. This label does not mean zero violations or guaranteed
  production safety; the per-request violation count is always reported.
- HIGH: at least two windows with pressure>1.
- Otherwise AMBIGUOUS. Equal to1 is not a breach.

Only select rates with matching LOW/HIGH labels in BOTH seeds. Among ordered
low<high pairs, take the largest qualifying low then smallest qualifying high above
it. No qualifying pair means INCONCLUSIVE; do not expand rates/seeds in this batch.
Request-level failures are a validity stop, not a HIGH label. Running/waiting and
in-flight evidence inform interpretation; a HIGH label alone does not prove a
specific queueing cause. Causal claims need a subsequent focused test.

## Bounds and handoff

Each trace<=10,000 requests, owned run<=480s including startup<=240s, batch<=3000s
plus bounded owned cleanup. Expected approximately18–24 minutes with previous
startup times, six fresh engines. No automatic retries, no extra GPU experiment
after viewing the selection. Verify complete results/source hashes and back up
locally; confirm GPU idle before shutdown advice. Only after this review design a
separate low/high/low adaptive decrease/recovery experiment. No resume updates.
