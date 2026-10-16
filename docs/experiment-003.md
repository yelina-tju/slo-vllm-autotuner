# Experiment 003: evidence-aware scheduler search

## Question

Can vLLM's scheduler token budget move the maximum SLO-feasible offered load,
and how should an autotuner avoid declaring a winner from noisy P99 samples?

## Search variable and controls

The candidate variable is `max_num_batched_tokens` in {1024, 2048, 4096}.
Every valid comparison holds the following values fixed:

- Qwen2.5-1.5B-Instruct in FP16 on one RTX 4090 D;
- `max_num_seqs=256`, chunked prefill enabled and prefix caching disabled;
- 256 input tokens, exactly 64 output tokens and Poisson arrivals;
- 64 warm-ups followed by 1,000 measured requests;
- P99 TTFT <= 100 ms and P99 E2E <= 400 ms.

`max_num_batched_tokens` bounds the token work admitted to one scheduler step.
A very small value can fragment prefill work, while a very large value can make
an iteration longer and hurt requests waiting behind it. The best value is
therefore workload-dependent rather than monotonically "larger is better."

## Invalid screening branch retained as an audit trail

The first 1024 and 4096 trials accidentally set `max_num_seqs=128`. vLLM 0.19.1
selects 256 dynamically for this GPU and API-server mode. The change reduced
the CUDA-graph/KV scheduling profile and raised P99 E2E to roughly 492–551 ms.
Those files are retained but excluded from candidate evaluation because two
variables changed at once.

The launcher now uses `auto` by default and only emits a scheduler flag when an
experiment explicitly supplies it.

## Successive-halving search

At 25 req/s, one paired screening seed failed for every valid candidate:

| Batched-token limit | Goodput | P99 TTFT | P99 E2E | Status |
|---:|---:|---:|---:|:---:|
| 1024 | 24.19 req/s | 73.18 ms | 411.52 ms | fail |
| 2048 | 24.26 req/s | 66.52 ms | 415.18 ms | fail |
| 4096 | 24.24 req/s | 74.84 ms | 413.65 ms | fail |

The few-millisecond differences are too small to treat as a reliable ranking.
Instead of spending more trials proving that 25 req/s fails, the inner search
moved to 23 and 24 req/s with a common seed:

| Limit | 23 req/s P99 E2E | 24 req/s P99 E2E | 24 req/s status |
|---:|---:|---:|:---:|
| 1024 | 391.47 ms | 391.43 ms | pass |
| 2048 | 389.26 ms | 388.85 ms | pass |
| 4096 | 397.98 ms | 402.26 ms | fail |

4096 was paused by successive halving. The two surviving candidates received
two additional seeds at 24 req/s:

| Limit | Feasible trials | Mean goodput | Worst P99 TTFT | Worst P99 E2E | E2E headroom |
|---:|---:|---:|---:|---:|---:|
| 1024 | 3/3 | 23.716 req/s | 70.23 ms | 395.96 ms | 4.04 ms |
| 2048 | 3/3 | 23.724 req/s | 68.32 ms | 392.76 ms | 7.24 ms |
| 4096 | 0/1 at 24 | 23.460 req/s | 72.39 ms | 402.26 ms | -2.26 ms |

## Selection result

Both 1024 and 2048 reach an empirical robust capacity of 24 req/s under the
current three-repetition rule. Their mean goodput is effectively tied, so the
selector chooses **2048 tokens** using worst observed P99 E2E headroom as the
tie-breaker. 4096 has only an observed 23 req/s capacity and is not promoted.

The result is deliberately described as robust under the experiment policy,
not as a production SLA guarantee. Three of three successes still have a Wilson
95% lower confidence bound of only about 43.9%. More repetitions, longer windows
and a nonzero safety margin are required before deployment.

## What the autotuner now does

`evaluate_scheduler_search.py` loads only files assigned to each candidate,
validates embedded scheduler metadata, aggregates repetitions by offered rate,
and labels every point as robust feasible, provisionally feasible, unstable or
observed infeasible. It maximizes robust capacity first, then uses conservative
tail headroom and goodput to break ties.

This is the first complete constrained-search loop:

1. screen configurations cheaply at a difficult load;
2. eliminate clearly poor candidates;
3. locate each survivor's feasible-load boundary;
4. spend repetitions only near that boundary;
5. select only from SLO-feasible evidence and preserve uncertainty.

## Next experiment

Repeat the comparison for a prefill-heavy and a decode-heavy request shape.
The expected result is not one universal number, but a policy that maps observed
workload features to a safe scheduler configuration. That workload-conditioned
policy is the bridge from an offline search script to an online autotuner.
