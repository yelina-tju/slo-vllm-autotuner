# Online admission v2 — prototype protocol

Status: CPU + loopback HTTP prototype, not connected to a vLLM backend. Existing v1 evidence
and performance claims remain frozen. No GPU launch is scheduled automatically.

Question: when workload/capacity drifts, can feedback admission outperform a
fixed measured catalog without excessive SLO violations or oscillation?

Initial method: bounded additive increase / multiplicative decrease (AIMD),
with a latency deadband, minimum samples, demand gating, settling time and an
explicit actuator acknowledgement. This is the simple baseline, not a novel
optimal estimator. A rate admitted successfully is not proof of backend capacity.

For each class c, rho_c=max(P99_TTFT_c/SLO_TTFT_c, P99_E2E_c/SLO_E2E_c).
Decrease if a sufficiently sampled class has rho_c>1 or backend failures.
Increase only when every required class has enough samples, no failures,
rho_c<0.8, two consecutive eligible windows, and offered rate >= 0.9*current rate.
Otherwise hold. Default step +1 RPS, decrease factor 0.7, bounds [1,12] RPS,
initial 3 RPS, settling 20 s, minimum 30 outcomes/class/window.

These are explicit development defaults, not selected or validated GPU settings.
Thirty samples make a noisy P99; publish sample counts and test sensitivity
before freezing performance evaluation. Failure input excludes gateway 429/503;
those are separate availability outcomes. All failures may justify a decrease
without a defined latency percentile; missing latency must never permit growth.

Evidence protocol: disjoint completed windows with monotonic start/end times;
each window belongs to exactly one acknowledged rate revision. Discard mixed
revision or pre-settling evidence. Offered demand includes rejected requests.
Class membership is fixed per prototype instance. Real integration must either
recreate/reset the controller on a declared class-set change or explicitly
represent absent classes; do not silently remove an unobserved class to permit
growth. Latencies require completed streams, and pending/timeouts need separate
tracking before claiming safety during a stalled backend.

Actuation: proposal does not change applied rate. While pending, no new action
is proposed. Acknowledged success updates rate/revision and starts settling;
failure keeps the old rate/revision and also settles. The future gateway adapter
must serialize changes with lifecycle transitions, pause ownership and token
bucket updates. Do not call the v1 resume() method as a generic hot update: it
unpauses admission and refills the bucket.

First-stage acceptance: bounds, invalid input rejection, stale/overlapping-window
rejection, no growth on low demand or insufficient classes, two-window growth,
prompt decrease, no repeated proposals, failed-actuation preservation, settling.
Deterministic CPU checks establish state-machine behavior only, not performance
or a stability proof.

Next stages, in order:
1. Replay driver and gateway event adapter; test stalled streams and actuation
   concurrency without a GPU.
2. Isolated GPU pilot with one fixed backend configuration, calibrate controller
   settings on development traces, then freeze code/config before evaluation.
3. Paired unseen seeds for abrupt shift, gradual drift and bursts. Compare fixed
   measured catalog, existing binary/canary where comparable, and simple AIMD.
   Keep traffic, models, scoring and actuator semantics identical or ablate their
   differences. Measure goodput, class SLOs, violations, 429/503, settling time,
   rate changes and saturation. Preserve negative results.
4. Limited second-model confirmation only after primary results are reviewed.

No predeclared throughput gain, global optimality, production reliability or
cross-model result. GPU experiment count and full trace definitions will be
frozen after the pilot, before held-out evaluation.

## Stage 3 protocol amendment (supersedes completed-window-only prototype)

StreamingPilot uses disjoint ARRIVAL cohorts [start,end). A cohort is emitted in
order only after its arrival interval ends and all admitted members complete or
reach a per-request deadline. Newer pending cohorts do not block an older finalized
cohort. Rejections contribute to arrival demand, not backend outcomes. Width and
deadline default to 10/15 seconds for development only. Emission timestamp is
recorded separately from arrival end; acknowledgement uses actual actuation time.

A single accounted timeout can propose multiplicative decrease even below the
usual sample floor. This is a conservative fault trigger, not a P99 estimate.
Revision matching, settling and one-pending-proposal guards still apply. Mixed
revision cohorts have no actionable evidence (timeouts retained in audit only).
Late completions cannot undo or duplicate timeouts. Client request timeout exits
the HTTP context; actual backend cancellation must be verified on GPU separately.

Only bounded fixed-backend pilots are supported. The request-ID ledger is capped
at 100000 and exhaustion rejects further pilot requests explicitly. No live
lifecycle/class-set reset, production proxy, optimality or stability claim.
