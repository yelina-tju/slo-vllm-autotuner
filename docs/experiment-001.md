# Experiment 001: concurrency sweep on one RTX 4090 D

## Question

How far can concurrency be increased before the serving configuration violates
the tail-latency SLO?

## Fixed conditions

- GPU: NVIDIA GeForce RTX 4090 D, 24 GB
- Driver: 580.76.05
- vLLM: 0.19.1
- PyTorch: 2.10.0+cu128
- Model: Qwen2.5-1.5B-Instruct, FP16
- Prompt/output: 256/64 tokens
- Requests per run: 64, all successful
- Candidate concurrency: 1, 4, 8, 16, 32
- SLO: P99 TTFT <= 100 ms and P99 E2E <= 400 ms

## Result

| Concurrency | Output tok/s | P99 TTFT | P99 E2E | Feasible |
|---:|---:|---:|---:|:---:|
| 1 | 224.47 | 31.33 ms | 288.50 ms | yes |
| 4 | 786.04 | 50.68 ms | 339.84 ms | yes |
| 8 | 1451.87 | 81.09 ms | 364.31 ms | yes |
| 16 | 2748.12 | 97.85 ms | 377.46 ms | yes |
| 32 | 3721.66 | 326.16 ms | 637.79 ms | no |

The offline selector chooses concurrency 16: it has the highest measured output
throughput among configurations satisfying both SLO constraints.

## Validity note discovered in Experiment 002

vLLM 0.19.1 enabled prefix caching by default, while repeated benchmark commands
reused the same random seed and therefore the same prompts. Later runs could hit
KV entries created by earlier runs. This sweep remains useful as a harness
smoke test and as evidence of the cold-compilation effect, but concurrency 16 is
an exploratory result rather than a cache-free capacity claim. A controlled
rerun must explicitly disable prefix caching or deliberately vary prompt seeds.

## Important cold-start observation

The first concurrency-8 run triggered compilation for a new shape. Its P99 TTFT
was about 9.48 seconds, versus 81.09 ms after warm-up. A production tuner must
therefore model warm-up state explicitly instead of mixing cold and steady-state
measurements.

## Next experiment

Repeat the sweep under open-loop Poisson arrivals and vary request rate. Optimize
goodput (requests meeting the SLO per second), not raw throughput alone.
