# Evaluation gates after the paired alignment development batch

Planning only; no new GPU batch is authorized by this file. Review all four
alignment runs, including failures and source/accounting audits, before choosing
the next frozen protocol. Do not change the running alignment experiment.

## What the current experiment can answer

Both arms adapt their admission rate. The treatment is evidence-window alignment,
not adaptation versus a static policy. The upper rate bound is deliberately six;
reaching it does not identify GPU capacity, convergence, or optimal goodput.

## Next bounded sequence

1. **Static comparison / accounting gate.** Prepare a runner that can set a fixed
   rate independently of adaptive initial rate. Test its CLI/config validation,
   exact trace reuse, no-actuation path and independent per-request audit without
   GPU. Define static 3 and static 6 as endpoint baselines, explicitly NOT a best
   static oracle. Any best-static claim needs a separate development sweep and
   frozen selection rule before held-out evaluation.
2. **SLO-pressure gate.** Before measuring a decrease/recovery benefit, define a
   bounded pressure scenario that actually crosses the frozen SLO, not merely a
   high offered arrival rate rejected by admission. Fix load/model/sequence
   limits, maximum runtime and stopping/cleanup criteria before execution. Keep
   SLO breaches as measured outcomes; only plumbing corruption invalidates an
   experiment. Do not search for a favorable seed after viewing results.
3. **Held-out gate.** Freeze algorithms, rates, workloads, metrics and seeds before
   running a new evaluation set. Use identical traces and balanced run order,
   fresh engines and identical warmups. Report per-seed differences, rejected
   demand, SLO violations and action timing. A small set supports descriptive
   evidence, not strong distributional claims.
4. **Mixed-class gate.** Resolve evidence starvation first; see
   SAMPLE_BUDGET_NOTES.md. Test absent/rare classes, changing class proportions,
   old evidence, timeouts and independent class SLOs. Do not reduce the sample
   floor solely to produce growth. Lifecycle resynchronization remains a separate
   integration gate; current live backend stays fixed throughout each mode.

## Why configured RPS is not observed throughput

The inherited gate has token capacity max(1, rate * 0.25). It rejects immediately
when fewer than one token remains; it does not queue until a token is available.
Bursty Poisson arrivals can therefore leave refill capacity unused while rejecting
nearby requests. Backend CPU/GPU utilization may stay low by design.

For the special stationary case with capacity exactly one, constant refill r and
Poisson offered rate lambda, each accepted request empties the bucket. The next
acceptance requires refill time 1/r plus the wait for the next Poisson arrival,
whose mean is 1/lambda. Thus the long-run expected accepted rate is

```text
a = 1 / (1/r + 1/lambda) = r*lambda / (r+lambda).
```

This derivation assumes immediate admission decisions, no pauses/rate changes,
and an ideal Poisson source. It is NOT a GPU throughput model and does not apply
unchanged when capacity exceeds one (rates above four in the present gate), to
finite transient phases, or to arbitrary traffic. Always measure actual admitted
throughput and class samples; do not infer them from the rate setting.

## Reporting boundary

Keep v1 results and career materials frozen during this extension. Only merge v2
claims after evidence coverage is clear. Distinguish correctness checks, real-GPU
development findings, held-out performance, and untested production integration.
