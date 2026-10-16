# Frozen bounded coarse bracket protocol: dev307–308 v1

Frozen before the first GPU case. This supersedes the coarse draft for this batch only.
No change to the adaptive controller, model, engine flags, SLO, or previous evidence.

## Sequential decision rule

Seed 307 tests static admission rates 18, 24, 36, 48 RPS in that order.
Stop ascending at the first HIGH. Select the greatest earlier LOW in this same trace;
AMBIGUOUS is not an eligible anchor. No earlier LOW means stop inconclusive.
No HIGH by 48 means stop inconclusive, without adding rates or seeds.
With a candidate pair, seed 308 repeats HIGH first, then LOW. Stop immediately if
either classification fails to replicate. Both must match for candidate_found.
At most six cases. No automatic recovery experiment, retries, or automatic resume.
An existing output directory is an error, never an instruction to overwrite it.

## Workload and measurement

Each seed has one deterministic Poisson 72 RPS offered trace lasting 120 seconds,
reused exactly across its static rates. Seeds are 307 and 308; at most 10,000 arrivals.
Balanced profile: 256 input tokens, 64 output tokens, TTFT 100 ms and E2E 400 ms SLO.
Fresh owned engine and four identical warmups per case; engine flags and frozen V1
dependencies must match the prior static endpoint batch. No adaptive actuation.

Six 20-second evidence windows each require at least 30 successful requests and
zero backend failures. Pressure is max(P99 TTFT / 100 ms, P99 E2E / 400 ms).
LOW requires all windows and whole-run pressure <= 1 and completed violation
fraction <= 1%. HIGH requires at least two windows above 1. Otherwise AMBIGUOUS.
Invalid accounting, driver, backend, or telemetry is a hard batch failure, not HIGH.
Primary goodput and request accounting are reconstructed independently from logs.

## Bounds and safety

Client timeout 10 s; pending-task cap 128; dispatch lag <= 0.25 s; ticks 0.25 s.
Telemetry every second with HTTP timeout 2 s. Require >=100 samples within traffic,
coverage >=110 s, gap <=3 s, and each scrape <=0.5 s. Save raw metrics for audit.
Sampled queue zero cannot exclude short queues between scrapes.
Startup <=240 s, each case <=480 s, batch <=3000 s plus owned-process cleanup.
Only the experiment's process group may be stopped. Failures halt the sequence.
Each valid case gets an exclusive checkpoint before another case may start.
Both traces and source/config hashes are saved before running cases.

## Interpretation

A replicated pair is a development calibration bracket, not an optimal rate,
held-out generalization, causal queueing proof, or successful controller recovery.
Selection stops early and is intentionally not an exhaustive capacity sweep.
The adaptive maximum 6 and growth margin 0.8 remain unchanged. A separate reviewed
recovery protocol is required before any further GPU work.
