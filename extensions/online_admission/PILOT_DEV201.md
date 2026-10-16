# Development smoke dev201-attempt1 — 2026-09-13

## Outcome

First actual vLLM integration smoke passed, including independent request/cohort
accounting and owned process cleanup. This is not final performance evidence.

| Mode | Offered | HTTP 200 / SLO-compliant | HTTP 429 | Goodput (req/s) |
|---|---:|---:|---:|---:|
| Fixed admission 3 RPS | 969 | 264 / 264 | 705 | 2.2000 |
| Feedback admission | 969 | 302 / 302 | 667 | 2.5167 |

Both: zero admitted backend failures, zero unfinished requests, all six arrival
cohorts finalized. Goodput counts per-request TTFT and E2E compliance divided by
the 120-second offered-traffic interval (including outcomes finalized in drain).
Also recomputed with client dispatch lag added to latency: same compliant counts.
Maximum dispatch lag: fixed 2.449 ms, adaptive 2.486 ms.

The descriptive difference is +0.3167 req/s (+14.39%) against fixed **3 RPS only**.
This is intentionally a low initial-rate plumbing baseline, not the strongest
static policy, not the old project's best measured policy, and not an estimate
of the value of feedback versus a properly tuned static baseline. Do not put
this percentage in the resume as a validated optimization achievement.

## Frozen setup and scope

- RTX 4090D 24GB; local Qwen2.5-1.5B-Instruct; FP16; max-model-len 4096;
  GPU memory fraction .75; batched tokens 1024; max sequences 256; FCFS;
  chunked prefill on; prefix caching off.
- balanced profile: 256 input / 64 requested output tokens, ignore_eos,
  temperature 0, reproducible synthetic token-ID prompts.
- SLOs taken from frozen release configs/workload_profiles.json:
  TTFT 100 ms, E2E 400 ms. These are old experimental budgets, not a new
  calibration or production SLA. Source hash is in manifest.json.
- Poisson arrivals, development seed 201; phases 40s at 6 RPS, 40s at 10 RPS,
  40s at 6 RPS. Identical saved arrivals/prompts in both modes.
- Cohort width 20s, timeout 10s, tick .25s; initial/min/max admission 3/1/6;
  additive step 1, decrease .7, pressure threshold .8, minimum 30 samples,
  two confirmations, settling 20s.
- Four warm-up requests, then fixed followed by adaptive on the SAME backend.
  No randomized order or independent restart between modes; cache is disabled
  but other warm-state/order effects remain. One seed cannot establish a CI.
- All three offered phases used the same request shape and remained above the
  initial admission limit. This does not establish capacity-drift handling,
  fault recovery, cross-model generalization or proximity to optimal capacity.
- Token-bucket rate is not achieved accepted throughput: Poisson arrivals and
  finite burst capacity yield idle gaps/rejections even below backend capacity.

## What the controller actually did

At 40.1226s it applied 3 -> 4 RPS after two healthy cohorts with sufficient
demand and samples. At 120.0971s it applied 4 -> 5 RPS AFTER offered traffic
ended. That terminal action did not validate service at 5 RPS or cause the
measured goodput difference. The useful in-traffic transition was 3 -> 4 only.

The [40,60) cohort mixed rate revisions around the first change and was
discarded. The [60,80) cohort began before the actual settling deadline
(approximately 60.12s), so it was discarded too. This demonstrates conservative
window alignment overhead: a tiny boundary offset can cost an entire 20-second
cohort. No settings were changed during the run to hide this behavior.

## Post-run fix — NOT part of the above GPU result

After preserving source/results, added a drain-only tick policy. At/after the
offered-traffic deadline, cohorts are still finalized/logged but no new actions
are proposed. The gate also checks the deadline inside its lock, so an earlier
proposal delayed behind a lifecycle lock cannot apply after expiry.

Current extension: 35 CPU/HTTP/audit tests passed, including terminal hold and
delayed-actuator expiry. Frozen v1: 102 tests passed. The pre-GPU extension had
31 passing tests. The post-run fix has NOT been rerun on GPU; previous outputs
remain unchanged and continue to show the terminal action honestly.

## Evidence and recovery

Local files relative to repository parent:

- work/online-admission-dev201-attempt1/: backend.log, manifest.json, trace.json,
  owned_process.json, report.json, fixed/adaptive requests.jsonl,
  control.jsonl, summary.json, and independent audit.json.
- work/online-admission-dev201-source/: exact executed source snapshot.
  All 14 Python files listed in manifest source_files match their SHA-256 hashes.
- Source used for GPU: cloud /root/autodl-tmp/online-admission-pilot-v4.
- Post-run CPU fix: cloud /root/autodl-tmp/online-admission-drainfix-v5.

The owned process group stopped and its leader exited 0. External final check
reported GPU 0 MiB / 0% and no model/driver process. Original source/results and
career materials were untouched. No extra GPU rerun was performed.

Read-only local audit (standard library only):

```sh
python extensions/online_admission/audit_pilot.py ../work/online-admission-dev201-attempt1
```

GPU reproduction uses the saved executed source for this exact result. Current
source contains the drain fix and must use a NEW output directory. The runner
refuses existing output directories, busy GPU and occupied port; startup timeout
240s, overall experiment timeout 600s, followed by bounded process cleanup.

## Next experimental questions

1. Quantify the cohort/settling alignment cost without weakening stale-evidence
   protection. Do not merely reduce safety timers until throughput looks better.
2. Verify GPU-side cancellation and bounded backlog on timeout, retaining real
   backend metrics; no such fault was exercised by this healthy smoke.
3. Compare against calibrated fixed rates with controlled run order, workload
   shifts and independent seeds before claiming performance improvements.
