# Stage 11 frozen bounded expansion — 2026-09-20

Motivation: stage10's six3/6/9 runs were valid but all LOW. Do not repeat them or
change SLO thresholds. This is a new development batch, not a held-out evaluation.

Exactly six runs: seed305 fixed6/12/18; seed306 fixed18/12/6. Each120s,
constant Poisson36 offered RPS, identical per-seed arrival/prompt traces across
rates. Keep6 as the within-batch low anchor. Offered load is higher than stage10,
so direct cross-batch throughput differences are not optimization gains.

Inherit all stage10 engine, model, warmup, SLO, telemetry, classification,
validity and stopping rules from PRESSURE_CALIBRATION_PROTOCOL.md. Only the
registered protocol identity, seeds, fixed-rate ladder and offered rate change.
Qwen2.5-1.5B, FP16, balanced256/64 tokens, TTFT100ms/E2E400ms; fresh owned engine
and four warmups per run. No adaptive bound/threshold change: this is static only.

LOW requires all six20s windows pressure<=1, whole-run pressure<=1 and completed
request violation fraction<=1%; HIGH requires at least two windows>1. Otherwise
AMBIGUOUS. At least30 successful outcomes per window, zero backend failures.
Choose only a low/high pair replicated across BOTH305/306: largest low, smallest
high above it. Otherwise INCONCLUSIVE. No additional seeds, rates or retries in
this batch, regardless of effect sign. Do not launch recovery automatically.

Bounds unchanged: trace<=10,000 requests, pending client tasks<=128, timeout10s,
dispatch lag<=.25s, run<=480s, startup<=240s, batch<=3000s plus owned cleanup.
Queue sampling1s, HTTP timeout2s; >=100 within-traffic samples spanning>=110s,
no gap>3s, scrape<=.5s. Backend/client/telemetry/accounting/cleanup failure stops
remaining runs after bounded cleanup; completed SLO breaches remain valid data.
Expected18–24 minutes. Raw logs, source hashes, cases and unsuccessful outcomes
must be backed up. Review all six before preparing a distinct recovery protocol.
