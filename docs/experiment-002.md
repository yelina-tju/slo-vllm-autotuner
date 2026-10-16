# Experiment 002: open-loop Poisson arrivals and goodput

## Question

At what offered request rate does queueing cause the service to violate its
tail-latency SLO, and how does SLO-compliant goodput differ from raw throughput?

## Workload and SLO

- Model: Qwen2.5-1.5B-Instruct, FP16 on one RTX 4090 D.
- Server: vLLM 0.19.1, max model length 4096, GPU memory utilization 0.75.
- Request shape: 256 input tokens and exactly 64 output tokens.
- Open-loop Poisson arrivals (`burstiness=1.0`) with no client-side concurrency
  cap, so overload remains visible.
- Request-level and window-level thresholds: TTFT <= 100 ms and E2E <= 400 ms.

Raw throughput counts every successful response. Request goodput counts only
responses satisfying both latency thresholds. Window feasibility is stricter:
the measured P99 TTFT and P99 E2E must both satisfy the SLO.

## Pilot and confounder discovery

The 100-request pilot initially appeared to place the boundary between 45 and
50 req/s. Repeated long runs then produced a suspicious pattern: the first rate
in every shell invocation was slow, regardless of whether that rate was 30, 45
or 50 req/s, while later rates were faster.

The vLLM metrics endpoint explained the inversion:

- `enable_prefix_caching="True"` was the effective default;
- 1,621,680 of 2,518,016 queried prompt tokens had hit the local prefix cache;
- benchmark commands in a sweep reused a seed and regenerated the same prompts.

Later rates were therefore replaying prompts whose KV state had been populated
by earlier rates. Those runs are retained as diagnostic evidence but are not
used for the cache-free capacity conclusion.

## Corrected baseline protocol

- Restart the server with `--no-enable-prefix-caching`.
- Confirm `enable_prefix_caching="False"` from `/metrics`.
- Use 64 unmeasured warm-up requests before every measured window.
- Use 1,000 measured requests and a different seed for each rate.
- Save per-request TTFT, ITL and start times plus a Prometheus snapshot.

## Corrected results

| Offered req/s | Achieved req/s | Goodput req/s | Request compliance | P99 TTFT | P99 E2E | Window feasible |
|---:|---:|---:|---:|---:|---:|:---:|
| 20 | 19.88 | 19.88 | 100.0% | 65.90 ms | 385.23 ms | yes |
| 30 | 29.72 | 27.91 | 93.9% | 75.20 ms | 445.57 ms | no |
| 40 | 39.50 | 24.61 | 62.3% | 83.97 ms | 515.13 ms | no |
| 50 | 49.15 | 10.32 | 21.0% | 103.30 ms | 541.68 ms | no |

The analyzer selects 20 req/s as the highest measured cache-free, SLO-feasible
rate. The current capacity interval is therefore **20–30 req/s**, not an exact
optimum yet.

## Interpretation

E2E latency becomes the binding constraint before TTFT: at 30 and 40 req/s the
TTFT SLO still passes, but the E2E SLO fails. Raw request throughput also keeps
increasing under overload while goodput peaks and then collapses. At 50 req/s
all 1,000 requests returned successfully, yet only 21% met both latency targets.

This experiment also demonstrates why a serving tuner needs controlled cache
state, sufficiently long windows, multiple seeds and explicit safety margins.
Otherwise it can optimize benchmark history instead of the serving system.

## Repeated boundary search

The follow-up used three seeds per rate and a Latin-square execution order so
that a particular rate was not always first or last. Each trial still contained
64 unmeasured warm-ups and 1,000 measured requests.

| Offered req/s | Feasible trials | Mean goodput | Worst P99 TTFT | Worst P99 E2E | Empirical status |
|---:|---:|---:|---:|---:|:---:|
| 22 | 3/3 | 21.75 req/s | 75.56 ms | 395.76 ms | pass |
| 25 | 1/3 | 24.39 req/s | 80.23 ms | 415.18 ms | unstable |
| 27 | 0/3 | 25.95 req/s | 78.37 ms | 420.04 ms | fail |

The measured capacity interval narrows to **22–25 req/s**. Under the project's
current rule (at least three repetitions and a 100% observed window pass rate),
22 req/s is the empirical safe rate. It has only 4.24 ms of worst-case E2E
headroom, however, and three passes do not establish production reliability:
the 95% Wilson interval for a 3/3 pass count is approximately [0.439, 1.000].

## Next experiment

Use the boundary as the inner load-search problem while comparing scheduler
configurations. Prefix caching will later be reintroduced as an explicit
configuration paired with controlled prefix-reuse workloads instead of
accidental prompt replay.
