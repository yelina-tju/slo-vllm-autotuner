# Stage 3 — arrival cohorts and streaming HTTP integration

## Implemented and checked

1. Arrival cohorts finalize in order after all admitted members finish or reach
   their deadlines. Later pending requests cannot block an earlier completed
   cohort. Ordered delivery delay is bounded by the configured request deadline
   plus the caller's tick interval (assuming the event loop continues running).
2. Timeouts count once as failures, carry a separate timeout count, and can
   decrease admission below the statistical sample floor. No fabricated P99 or
   fabricated sample counts. Mixed/stale revisions cannot justify promotion.
3. Deadline heap avoids scanning the entire historical request ledger per event.
   Retained IDs are capped for bounded runs; this is not a production eviction
   design. Completion at or after the deadline is a timeout by definition.
4. StreamingPilot performs real HTTP calls and incremental SSE token/DONE
   parsing against an aiohttp loopback test server. It is a pilot client, not a
   replacement public proxy. Admission and revision assignment share the
   executor lock; network I/O does not hold that lock.
5. Timeout/client cancellation releases in-flight admission. Truncated SSE is a
   failure. Paused rejection stays a gateway outcome. Concurrent ticks are
   serialized and cannot double-apply a growth proposal.

## Executed validation

Local pure-Python cohort suite: 5 passed.
Cloud extension suite against frozen release src: 28 passed in 0.476 seconds.
Cloud frozen v1 regression suite: 102 passed in 0.160 seconds.
Final GPU check: 0 MiB used, 0% utilization. No vLLM backend was launched.
The HTTP integration tests bind only 127.0.0.1 and close sessions/server runners.

Cloud staging directory: /root/autodl-tmp/online-admission-cohorts-v3.
Frozen source and preceding stage directory were not overwritten.

```sh
cd /root/autodl-tmp/online-admission-cohorts-v3
PYTHONPATH=/root/autodl-tmp/release-final/src /root/autodl-tmp/envs/vllm-autotuner/bin/python -m unittest discover -s . -p 'test_*.py' -q
```

## Interpretation and remaining work

Continuous-traffic liveness is demonstrated by a deterministic event-stream test;
it is not a GPU throughput result. HTTP tests independently cover successful
evidence-to-rate actuation, stalled response-to-decrease, cleanup, and failure
classification. Test-only thresholds use tiny windows/sample floors to make
tests fast; do not reuse those settings as benchmark calibration.

Before GPU: implement bounded open-loop runner and structured per-request,
cohort, decision and applied-rate outputs; validate SLO provenance; configure
timeouts and process ownership cleanup. Begin with a fixed backend and a paired
static/adaptive development smoke run, not a claim of optimality or a held-out
performance comparison. Any lifecycle/model/class change requires an explicit
controller reset contract before it is enabled.

Client disconnection does not prove vLLM work cancellation. Pending backlog and
backend cleanup require inspection during the GPU pilot. Timeout signals remain
subject to revision/settling guards, so this is not an independent universal
watchdog. Evidence-age sensitivity, larger sustained-load tests and memory
behavior remain evaluation tasks. No career material or historical metric changed.
