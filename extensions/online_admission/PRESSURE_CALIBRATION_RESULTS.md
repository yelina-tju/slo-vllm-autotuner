# Stage 10: bounded pressure calibration — 2026-09-19

## Outcome: valid experiment, pressure bracket not found

All six frozen runs completed without retries, extra seeds, changed thresholds or
extra GPU experiments. Independent local audit passed. All six runs classified LOW
under the preregistered rule; none classified HIGH. The selection result is
`inconclusive`: no replicated low/high operating pair was found within3/6/9 RPS.

This is not a controller decrease/recovery pass. No adaptive controller ran in this
batch. It also does not prove a global safe capacity, optimal rate, or production
reliability. Keep the distinction between successful experiment execution and
achieving the scientific objective of identifying a pressure boundary.

## Frozen design and complete results

Six fresh engines, Qwen2.5-1.5B FP16 on one4090D, unchanged engine flags and
balanced256-input/64-output shape; TTFT100ms/E2E400ms. Each120s, identical per-seed
Poisson18 RPS arrivals/prompts across fixed rates. Seed303 order3/6/9; seed304
order9/6/3. Four identical warmups each. See PRESSURE_CALIBRATION_PROTOCOL.md.

| Seed | Fixed rate | Offered | Compliant | Rejected429 | Goodput req/s | P99 TTFT ms | P99 E2E ms | Breached windows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 303 | 3 | 2157 | 309 | 1848 | 2.5750 | 28.30 | 285.22 | 0/6 |
| 303 | 6 | 2157 | 667 | 1490 | 5.5583 | 32.21 | 308.58 | 0/6 |
| 303 | 9 | 2157 | 1035 | 1122 | 8.6250 | 30.93 | 324.38 | 0/6 |
| 304 | 9 | 2204 | 1040 | 1164 | 8.6667 | 31.78 | 323.98 | 0/6 |
| 304 | 6 | 2204 | 675 | 1529 | 5.6250 | 31.65 | 306.54 | 0/6 |
| 304 | 3 | 2204 | 310 | 1894 | 2.5833 | 27.15 | 286.87 | 0/6 |

Total13,083 offered records,4,036 admitted successes meeting both SLOs,9,047
admission rejections. Zero backend failures, completed-request SLO violations,
static actuation, final in-flight requests or pending primary cohorts. P99 is
nearest-rank whole-run service latency, not the per-window selection statistic.
Scheduled-arrival and actual-admission-adjusted goodput matched service goodput
in all six cases. Maximum actual admission lag was about7.838ms.

## Useful partial finding: growth headroom versus violation boundary

For each complete20s window, the measured pressure is

```text
pressure = max(P99_TTFT / 100ms, P99_E2E / 400ms).
```

| Rate | Mean compliant goodput | Window pressure range across both seeds | Windows below growth threshold0.8 | Windows in [0.8,1] |
|---|---:|---:|---:|---:|
| 3 | 2.5792 | 0.7012–0.7353 | 12/12 | 0/12 |
| 6 | 5.5917 | 0.7556–0.7734 | 12/12 | 0/12 |
| 9 | 8.6458 | 0.8058–0.8287 | 0/12 | 12/12 |

Thus the tested evidence crosses the existing growth-headroom threshold, but not
the SLO-violation threshold. The protocol's LOW label means SLO-compliant by its
rule, NOT necessarily eligible for growth. At9 the measured pressure is in the
controller's deadband: evidence would not justify further growth under that
threshold. This is interpretation of static measurements, not a measured online
controller decision or proof that9 is optimal. The deployed adaptive bounds remain
unchanged at maximum6; they were not raised by this experiment.

## Telemetry interpretation

Each case had117 valid within-traffic queue samples:702 total, with raw metrics
retained. Maximum sampled backend running requests by rate were1 at3, up to3 at6,
and4 at9. Sampled waiting counts were zero throughout. Reconstructed client
in-flight peaks were1/3/5 for rates3/6/9. These are different measurements and need
not be equal; a1s sampler can miss brief queues. Do not claim that zero sampled
waiting proves no queueing ever occurred.

The slowest metrics scrape was29.411ms, within the frozen500ms cutoff. Sampling
was enabled identically for all arms, but its incremental overhead was not measured
with an on/off ablation. Do not present scrape latency as total controller overhead.

This batch used constant offered18 RPS, unlike the earlier6/10/6 trace. Higher
goodput relative to the previous batch must NOT be called an optimization gain:
arrival distribution, timing and possibly host state differ. Likewise the lower
tail latencies observed here cannot be confidently attributed to one cause.

## Verification and provenance

- Prelaunch frozen snapshot:81 CPU/HTTP tests passed in1.607s, including exact
  trace agreement with the existing driver, queue parser and real loopback sampler.
- Seven further local telemetry-analysis tests passed during the GPU batch:
  valid evidence, parsed/raw mismatch, scrape failure, insufficient coverage,
  large sampling gap, slow scrape, and under-sampled latency. They mock the base
  request auditor to isolate telemetry gates; they do not independently re-prove
  request accounting. They are not part of the81-test combined run.
- Frozen v1 regression after GPU completion:102 tests passed in0.158s.
- Local batch auditor reconstructed request counts, unique IDs, class quantiles,
  static rates/revisions, raw metric parsing, telemetry coverage, six-window
  classifications, case order and final selection. All41 executed Python source
  hashes and config hash verified. SLO and frozen-v1 dependency hashes match the
  prior static batch. Engine commands match except the private port; model-config
  hashes, all warmups and all cleanup records match requirements.
- Running remote source/configs remained unchanged. The later offline batch
  auditor and seven local test cases were not used to execute the GPU batch.
  No v1 source or resume/interview material was changed.

## Evidence archive and cloud state

Relative to repository parent:

```text
work/pressure-calibration-sep19-evidence.tar.gz
work/pressure-calibration-sep19-evidence/pressure-calibration-v12/online_admission/
work/pressure-calibration-sep19-evidence/online-admission-pilot-results/
    pressure-dev303-304-attempt1/
work/pressure-calibration-sep19-audit.json
```

Archive SHA256 (local/remote match):
`b073ff04df46bda4ba05165d5b321ca2a784b1e5a6788f194ca67526dcea2d24`.

197 archive members checked for safe paths and ordinary file/directory types
before extraction to a new local directory. Remote originals retained. Final
compute-process query was empty, with no pressure runner or vLLM serve process
remaining. It is safe to shut down the instance; future boundary/recovery tests
still require GPU access, so deletion is not recommended yet.

## Next decision, not an extra run hidden in this batch

Do not repeat3/6/9 or tighten the SLO to force a positive result. The next bounded
development protocol should retain a low anchor and test a larger but explicitly
capped range, with enough offered load to exercise that range. One candidate for
review is fixed6/12/18 with offered36, two new development seeds and the same
request shape/SLOs. This is a proposal, NOT frozen configuration or measured data;
driver-task limits, trace sizes, telemetry and stop rules must be checked first.

Only after a replicated low/high bracket exists should a separate controlled
decrease/recovery trial be frozen. Before that, it is still possible to test code
paths with synthetic faults, but not claim real overload recovery or adaptive
goodput superiority. Held-out and mixed-class evaluation remain later gates.
