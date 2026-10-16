# Stage 11 bounded pressure expansion — 2026-09-20

## Outcome

Six frozen6/12/18 RPS runs completed, independently audited and backed up locally.
All classified LOW. No replicated low/high pair exists: selection remains
INCONCLUSIVE. The experiment ran successfully; the pressure-boundary objective
has not yet been achieved. This is not validation of adaptive decrease/recovery.

No extra GPU experiments, retries, threshold changes or seed additions followed
the result. Original stage10 evidence remains unchanged; the new auditor was also
run against it and passed, preserving its original inconclusive conclusion.

## Results

Same Qwen2.5-1.5B FP16, one4090D, balanced256-input/64-output shape,
TTFT100ms/E2E400ms. Each120s, fresh engine, four warmups, identical per-seed
Poisson36 RPS arrivals across rates. Seed305 order6/12/18; seed306 order18/12/6.

| Seed | Rate | Offered | Compliant | Rejected429 | Goodput req/s | P99 TTFT ms | P99 E2E ms | Breached windows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 305 | 6 | 4308 | 716 | 3592 | 5.9667 | 30.00 | 303.64 | 0/6 |
| 305 | 12 | 4308 | 1437 | 2871 | 11.9750 | 32.21 | 330.94 | 0/6 |
| 305 | 18 | 4308 | 2157 | 2151 | 17.9750 | 37.19 | 347.09 | 0/6 |
| 306 | 18 | 4381 | 2163 | 2218 | 18.0250 | 37.00 | 347.39 | 0/6 |
| 306 | 12 | 4381 | 1441 | 2940 | 12.0083 | 33.38 | 331.99 | 0/6 |
| 306 | 6 | 4381 | 716 | 3665 | 5.9667 | 29.35 | 304.61 | 0/6 |

Totals:26,067 offered records,8,630 admitted/compliant successes,17,437 rejections.
Zero observed completed-request SLO violations or backend failures. No static
actuation or final pending requests/cohorts. All36 evidence windows stayed <=1.
P99 values above are whole-run nearest-rank service latencies, not window ratios.
Scheduled-arrival and actual-admission-adjusted goodput matched service goodput.
Finite-trace token-bucket bursts can allow mean admissions slightly above the
configured rate, as in seed306 rate18; it is not an unbounded rate-setting error.

The mean goodputs are5.9667/11.9917/18.0000 for rates6/12/18. These are measured
static-rate results, NOT an optimization percentage. Offered traffic changed from
18 in stage10 to36 here; do not attribute cross-batch throughput changes solely
to configuration improvements or compare them as a controlled treatment effect.

## Pressure and telemetry interpretation

At6, window pressure remained below0.8; all12 windows at12 and all12 at18 were
in the0.8–1.0 deadband. At18 the maximum window pressure was about0.8745, still
below the violation threshold. The existing conservative growth margin can stop
growth while a higher static rate remains compliant. This reveals a tradeoff,
not proof that the margin should be relaxed or that18 is optimal.

There were701 valid within-traffic queue samples (five cases117, one116).
Maximum sampled running counts by rate were2/5/9; reconstructed client in-flight
peaks were3/6/10. Sampled waiting remained zero. A1s sampler can miss brief queues;
these observations do not establish a causal queueing model or prove no queueing.

Maximum actual admission lag was41.321ms in seed305 rate12, within the frozen
250ms cutoff; all scheduled SLO classifications still passed. Slowest metrics
scrape was69.999ms, within the500ms cutoff. Telemetry overhead was not separately
ablated and must not be described as total controller overhead.

## Supplementary generation-shape diagnostic

After execution, raw generation histogram count/sum metrics were parsed locally.
All samples in all six runs have cumulative mean output64 tokens and monotone
completion counts. This supports consistency with the requested output shape,
but is an aggregate diagnostic, not per-request token proof or a new inclusion
criterion. Counters can lag the last completion: final samples were missing0–6
completions relative to request logs plus four warmups. Request-level logs remain
the accounting authority. No primary result was rewritten or excluded.

## Verification and provenance

- Frozen cloud extension suite:92 CPU/HTTP tests passed in1.667s, including old
  protocol compatibility, registered expansion bounds, trace reproduction and
  selection isolation between seed sets. Four new expansion tests also passed
  locally before packaging.
- Original frozen v1 regression after GPU completion:102 tests passed in0.160s.
- Three supplementary generation-metric tests passed locally after correcting an
  initial syntax error in that local-only diagnostic. It was never part of the
  running GPU source and had no effect on the experiment.
- Local batch audit reconstructed request IDs/counts, per-window quantiles,
  no-actuation/revision invariants, raw metrics, coverage, all six classifications
  and final selection. All44 executed Python source hashes and config hash match.
  Model-config, SLO and frozen-v1 dependency hashes match the earlier baseline;
  engine commands match except the private service port. Warmups and owned cleanup
  passed for every run.
- Remote v13 remained unchanged throughout. Recovery-design notes and the local
  supplementary token diagnostic were prepared separately. No resume/interview
  materials, v1 source, adaptive bounds or growth thresholds changed.

Local evidence relative to repository parent:

```text
work/pressure-expansion-sep20-evidence.tar.gz
work/pressure-expansion-sep20-evidence/pressure-expansion-v13/online_admission/
work/pressure-expansion-sep20-evidence/online-admission-pilot-results/
    pressure-dev305-306-attempt1/
work/pressure-expansion-sep20-audit.json
work/pressure-expansion-sep20-generation.json
```

Archive SHA256 (local/remote match):
`469ef27525812ccbe295a9fbfed3c4a450f930838407e22aa8f52e0b447f32d4`.

205 archive members checked for safe paths/types before extraction to a new local
directory. Remote originals retained. Final GPU compute query was empty, with no
calibration runner or vLLM serve process remaining. Instance can be shut down;
future experiments still need GPU access. No instance deletion was performed.

## Method adjustment before the next GPU batch

Two valid calibration batches have now failed to reach a violating regime. The
tested ranges were too conservative for identifying the boundary of this model
and shape. Do not keep running six-case small expansions.

Prepare a bounded coarse search with early stopping, then replicate ONLY the
candidate low/high pair. See COARSE_BRACKET_PROTOCOL_DRAFT.md: provisional18/24/36/48,
offered72, <=six total runs including confirmation. This is a draft, not implemented
or executed. Freeze its sequential rules and tests before launch, and retain an
inconclusive outcome if the cap is insufficient. Avoid extrapolating capacity from
a short latency curve or forcing failures by tightening the SLO.

RECOVERY_DESIGN_DRAFT.md separately explains how to distinguish recovery caused
by actuation from recovery caused merely by offered load subsiding. Neither draft
establishes actual recovery performance; review a validated bracket first.
