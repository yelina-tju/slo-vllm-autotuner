# Next gate: distinguish admission pressure from backend SLO pressure

Draft written during static endpoint runs, 2026-09-15. Not an executable protocol,
not permission to start more GPU runs, and not a modification of this batch.
Review complete static results before freezing numerical settings.

## Question

Can a fixed backend demonstrate both a low-load SLO-compliant operating region
and a higher-load region with SLO breaches caused by admitted concurrency/queueing?
Only then is a decrease/recovery experiment informative. Rejected offered traffic
alone does not demonstrate backend overload. A successful easy-load increase test
does not validate overload safety or discovery of maximum capacity.

## Separate calibration from controller evaluation

1. Retain the balanced request shape and frozen TTFT/E2E thresholds initially.
   Verify low-load latency headroom from the static endpoint results. Do not make
   the SLO stricter just to manufacture a breach.
2. If the upper endpoint remains comfortably within SLO, prepare a bounded static
   rate ladder in a separate development protocol. Select the ladder, offered
   traffic rule, duration, repetitions and maximum cost BEFORE running; do not
   continually increase the bound until a favorable effect appears.
3. For each candidate, record admitted throughput, in-flight/queue evidence,
   TTFT/E2E distributions, rejected requests, backend failures and dispatch lag.
   High driver lag or a saturated client-task cap is a load-generator limitation,
   not evidence of backend SLO capacity. Preserve the failed attempt and diagnose.
4. Identify a tested low/high operating pair using a predeclared rule. If no pair
   exists inside the safety budget, report that calibration was inconclusive.
   Do not silently relabel offered-rate spikes as SLO-pressure events.
5. Freeze the selected scenario, adaptive bounds and initial condition before a
   distinct low/high/low controller trial. Compare an appropriate static endpoint
   and retain cost during ramp-up, violations during response, and recovery time.

## What a decrease/recovery pass must mean

- Fresh, post-settling evidence actually crosses its frozen SLO criterion or
  records a timeout; a qualifying decrease is acknowledged at the gate.
- Request conservation, revision attribution, bounded rates, no terminal
  actuation, and backend ownership/cleanup still pass.
- After returning to the low-load condition, report time until valid healthy
  evidence and, if demand warrants it, subsequent growth. No growth under low
  demand can be correct; do not count it automatically as failure.
- Report SLO-compliant goodput and rejected demand across the entire trace, not
  only the recovered tail. Compare against static using the same arrivals.
- A timeout path needs explicit cancellation evidence; earlier isolated tagged
  cancellation tests do not establish correctness for every new concurrency level.

## Unresolved before launch

The numeric rate ladder, per-run budgets, queue telemetry overhead, high-pressure
selection rule and stopping criteria still need to be frozen. Current bounds of
1–6 RPS are not a capacity estimate. Do not alter the adaptive bound in a running
experiment. Mixed-class evidence starvation and lifecycle resynchronization remain
separate gates and should not be bundled into the first pressure test.
