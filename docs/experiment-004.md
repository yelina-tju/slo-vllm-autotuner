# Experiment 004: workload-conditioned capacity

## Question

Does one SLO-aware capacity limit remain valid when request shape changes, and
does the scheduler token budget have a repeatable winner for long prompts?

## Workload-aware SLO calibration

End-to-end latency naturally grows with prompt and output length. Reusing the
balanced workload's 400 ms deadline for a 256-token output would make even an
idle server infeasible. The experiment therefore measures each workload's
concurrency-one P99 latency with prefix caching disabled, then preserves the
balanced workload's relative SLO headroom.

| Workload | Input/output tokens | Floor P99 TTFT | Floor P99 E2E | Calibrated TTFT/E2E SLO |
|---|---:|---:|---:|---:|
| balanced | 256/64 | 32.81 ms | 288.65 ms | 100/400 ms |
| prefill-heavy 4x | 1024/64 | 59.01 ms | 314.34 ms | 180/440 ms |
| decode-heavy 4x | 256/256 | 36.43 ms | 1076.31 ms | 115/1500 ms |

The calibration budgets are experimental normalization rules, not claims about
an external production SLA. `calibrate_workload_slos.py` derives them from raw
measurements and rounds upward to fixed quanta.

## Capacity changes with request shape

Using the selected 2048-token scheduler configuration, coarse search followed
by three repeated boundary trials produced:

| Workload | Repeated feasible point | Next measured point | Capacity status |
|---|---:|---:|---|
| balanced | 24 req/s, 3/3 pass | 25 req/s, 1/3 pass | robust 24; 25 unstable |
| prefill-heavy 4x | 3 req/s, 3/3 pass | 4 req/s, 2/3 pass | robust 3; 4 unstable |
| decode-heavy 4x | 18 req/s, 3/3 pass | 21 req/s, fail | robust 18; boundary 18–21 |

The safe admission rate cannot be a single server-wide constant. Long prompts
reduce the safe request rate sharply because Poisson bursts create expensive
prefill work and head-of-line interference. Long outputs sustain a higher
request rate than the prefill-heavy workload, but E2E latency remains the
binding constraint as decode steps accumulate.

Total token counts alone do not predict these boundaries. Prefill and decode
exercise different kernels, batching opportunities and scheduling paths, so an
online tuner needs prompt/output-shape features rather than only requests per
second.

## Token-budget comparison on the prefill-heavy workload

At 5 req/s, all three candidates fail the 440 ms P99 E2E target:

| `max_num_batched_tokens` | P99 TTFT | P99 E2E | Status |
|---:|---:|---:|:---:|
| 1024 | 99.01 ms | 471.62 ms | fail |
| 2048 | 102.54 ms | 476.09 ms | fail |
| 4096 | 97.56 ms | 481.32 ms | fail |

The monotonic P99 E2E ordering is consistent with shorter scheduler steps at a
smaller budget, but none crosses the SLO. At the 4 req/s boundary, the paired
results are not consistent:

| Seed | 1024 P99 E2E | 2048 P99 E2E | 1024 - 2048 |
|---:|---:|---:|---:|
| 33 | 421.90 ms | 436.09 ms | -14.20 ms |
| 35 | 424.48 ms | 417.79 ms | +6.68 ms |
| 36 | 441.47 ms | 440.55 ms | +0.92 ms |

Both candidates pass two of three windows. The mean paired difference is only
-2.20 ms and changes sign, so the data do not justify a workload-specific token
budget winner. 4096 is stopped early because it is worst at the harder 5 req/s
screen and had already underperformed on the balanced workload.

## Generated policy

`evaluate_workload_search.py` reloads raw per-request arrays using each
workload's calibrated SLO, recomputes goodput instead of trusting thresholds
embedded by an earlier run, validates workload and scheduler metadata, and
writes both an audit CSV and a machine-readable policy.

The current safe baseline policy is:

| Workload | Configuration | Robust capacity |
|---|---|---:|
| balanced | mbt2048-seq256 | 24 req/s |
| prefill-heavy 4x | mbt2048-seq256 | 3 req/s |
| decode-heavy 4x | mbt2048-seq256 | 18 req/s |

The repeated use of 2048 means "best supported safe fallback," not "universal
optimum." The important workload-conditioned output at this stage is the
admission capacity. A policy entry remains null whenever repeated evidence is
missing rather than silently promoting a pilot result.

## Next experiment

Homogeneous long prompts do not expose short-request starvation directly. The
next workload should mix short and long prompts, report SLO compliance per
class, and search vLLM's chunked-prefill controls:

- `max_num_partial_prefills`;
- `max_long_partial_prefills`;
- `long_prefill_token_threshold`.

This tests a specific mechanism: reserving prefill opportunities for short
prompts may reduce their head-of-line blocking while retaining throughput for
long prompts. It is a stronger next step than expanding an undirected grid over
more unrelated flags.
