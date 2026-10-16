# Experiment 005: mixed-class interference pilot

## Question

When 256-token interactive prompts share one vLLM server with 2048-token
document prompts, can scheduler controls protect the short class without
violating the long class's SLO?

## Workload and measurement

The new asynchronous harness sends deterministic Poisson arrivals to the real
streaming Completion API. It allocates an exact 80/20 class mix, uses distinct
random token-ID prompts, records every request's client-observed TTFT and E2E
latency, and evaluates each class against its own SLO.

| Class | Share | Input/output tokens | TTFT/E2E SLO |
|---|---:|---:|---:|
| interactive short | 80% | 256/64 | 100/400 ms |
| document long | 20% | 2048/64 | 295/500 ms |

The long-class SLO is calibrated rather than guessed. Its isolated
concurrency-one P99 floor is 96.30 ms TTFT and 353.84 ms E2E. Scaling the
balanced workload's 100/400 ms budget by the same floor-latency ratios and
rounding to the established quanta gives 295/500 ms.

Each pilot contains 160 requests: 128 short and 32 long. Prefix caching is off,
the model and prompts are paired by seed, and the server uses a 256-sequence
limit. A window passes only when both classes satisfy their P99 SLO and there
are no transport failures.

## Compatibility finding

The planned concurrent-partial-prefill candidate could not start. Although
vLLM 0.19.1 exposes `max_num_partial_prefills` and related flags in CLI help,
its engine configuration contains an unconditional unsupported-feature check
for any non-default concurrent partial prefill value. The failure occurred
before model allocation and was retained as a compatibility result; the
experiment did not bypass the guard.

Two supported mechanisms were tested instead:

- priority scheduling assigns priority 0 to short requests and priority 1 to
  long requests, so queued short requests are considered first;
- a 1024-token scheduler budget forces each 2048-token prompt into at least two
  chunks, creating more scheduling boundaries than the 2048-token baseline.

## Pilot results

| Candidate | Offered rate | Short P99 TTFT/E2E | Long P99 TTFT/E2E | Both classes pass |
|---|---:|---:|---:|:---:|
| mbt2048 + FCFS | 3 | 50.63 / 382.21 ms | 77.66 / 455.51 ms | yes |
| mbt2048 + FCFS | 4 | 60.57 / 421.09 ms | 80.02 / 463.98 ms | no |
| mbt2048 + FCFS | 6 | 77.07 / 474.88 ms | 97.76 / 466.80 ms | no |
| mbt2048 + FCFS | 8 | 98.31 / 477.37 ms | 108.28 / 482.01 ms | no |
| mbt1024 + FCFS | 3 | 50.12 / 377.14 ms | 88.51 / 455.69 ms | yes |
| mbt1024 + FCFS | 4 | 57.22 / 419.99 ms | 86.36 / 464.00 ms | no |
| mbt1024 + FCFS | 6 | 71.21 / 468.15 ms | 108.18 / 469.00 ms | no |
| mbt2048 + short priority | 6 | 65.80 / 470.60 ms | 97.31 / 467.40 ms | no |
| mbt2048 + short priority | 8 | 85.44 / 479.87 ms | 108.52 / 481.20 ms | no |

The seed-43 pilot places both FCFS candidates' observed boundary at 3–4 req/s.
This is not yet a robust capacity estimate because each point has only one
trial.

Priority scheduling consistently reduces short-class TTFT at 6 and 8 req/s,
but does not bring E2E latency under 400 ms. It can reorder waiting requests,
but cannot preempt a long prefill already executing. The 1024-token budget also
moves short E2E in the expected direction, but the improvement is too small to
shift the observed capacity boundary. Neither candidate is declared a winner.

## Repeated boundary confirmation

Seeds 44 and 45 were added with candidate and rate order counterbalanced. One
initial seed-44 file exposed a harness bug: a successful stream containing only
skipped special tokens had HTTP 200 and a complete E2E measurement, but no
visible text, so it was incorrectly labeled failed. Schema v2 requests vLLM's
`token_ids` and detects first-token arrival independently of detokenized text.
The invalid file is retained with an explicit suffix and excluded from all
patterns; the canonical seed-44 window was rerun.

| Candidate | Rate | Passing windows | Worst short P99 E2E | Worst long P99 E2E | Empirically safe |
|---|---:|---:|---:|---:|:---:|
| mbt2048 + FCFS | 3 | 3/3 | 383.55 ms | 455.51 ms | yes |
| mbt2048 + FCFS | 4 | 1/3 | 421.09 ms | 463.98 ms | no |
| mbt1024 + FCFS | 3 | 3/3 | 381.53 ms | 455.69 ms | yes |
| mbt1024 + FCFS | 4 | 1/3 | 419.99 ms | 466.20 ms | no |

Both candidates therefore have a robust capacity of 3 req/s under the project's
three-window, 100%-pass policy. The generated policy selects mbt1024 because it
has slightly more worst-case normalized E2E headroom at the tied capacity. This
is a deterministic tie-break, not a claim of a large or universal performance
advantage. The equally robust mbt2048 candidate is stored as rollback state.

Three successes still give a wide 95% Wilson interval (approximately
0.44–1.00), so “robust” here means supported by the declared empirical rule,
not statistical certainty.

## What the pilot establishes

The homogeneous-workload rate estimate does not transfer to a mixed workload.
An input-work conservation estimate suggested roughly 10 req/s, yet the short
class already violates its tail SLO at 4 req/s while the long class remains
healthy. Request rate and aggregate token rate therefore miss cross-class
interference that an SLO-aware controller must observe directly.

The repeated boundary and conservative mixed-workload policy are now complete.
The next step is workload-shift detection that selects between homogeneous and
mixed policies, while retaining the last robust configuration as rollback
state.
