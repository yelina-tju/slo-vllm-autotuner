# Phase-isolated recovery proposal: CPU preparation only

Integration update: dedicated260s runner/analyzer/auditor implemented;96 local
regression tests passed and real predecessor evidence was re-audited before a
local freeze. No GPU run started. See GUARDED_INTEGRATION_STATUS.md; the original
preparation record below describes the earlier implementation boundary.

2026-09-21. The old401/402 verdict remains inconclusive_baseline. This proposal
does not rescore old traces, change the controller, or launch a GPU experiment.

## Design

| Time (seconds) | Offered load | Purpose |
|---|---:|---|
|0–40|6 RPS|Two20s initial-state validation windows|
|40–60|6 RPS|Guard interval, still normal traffic and controller feedback|
|60–220|72 RPS|160s high-load episode|
|220–260|6 RPS|40s after phase|

Twenty seconds exceeds the10s request timeout plus0.25s dispatch budget and
preserves the existing20s grid alignment. This is an experimental isolation
margin, not an optimized value or proof that a timeout always fires on time.
The initial gate additionally checks actual completion before60s for every
initial arrival, including failed requests. Delayed finalization invalidates
that gate; sparse/empty windows cannot pass. Existing minimum30 successes,
P99 pressure<=1, violation fraction<=1%, zero admitted failures remain unchanged.

Guard traffic is NOT paused or drained by the controller. Requests started in
the guard may still cross the load step, and their SLO violations remain real.
The purpose is to isolate the earlier baseline measurement, not to eliminate
all cross-boundary interactions. The controller receives no future load labels.

Whole-trace scheduled goodput uses260s, not240s or a recovered-tail denominator.
Scheduled-arrival phase accounting partitions every offered request exactly
once; guard violations, rejected requests and backend failures remain included.
The actual-arrival initial gate is a separate measurement; these clocks must
not be silently substituted for one another.

## Evidence attribution and interpretation

Keep action acknowledgement time AND evidence arrival interval. An action at
60.6s based on[40,60) is pre-high-arrival evidence, even when those requests
completed during high load. It must not be called detection of a fully high-load
window. No controller action is disabled to manufacture a desired experiment.

The proposed primary question is operational recovery during high load, allowing
legitimate responses to boundary evidence but explicitly labeling them. A
separate claim of full-high-window detection requires an actual evidence interval
entirely inside[60,220); if absent, report that claim as not demonstrated. Do not
make it a post-hoc reason to repeat an otherwise completed experiment.

## Scope and gates before any new GPU use

Proposed unused seeds403/404; three arms each (fixed24,fixed48,adaptive from48),
same order pattern as before. CPU trace counts12,124 and12,150; cap14,000 each.
Exactly six runs if eventually launched;26 minutes of traffic plus lifecycle
overhead. No retry or adaptive seed search. Two seeds are descriptive, not a
statistical power or broad generalization claim. Changed duration/load protocol
means these results must not be pooled with the240s batch as identical trials.

Model, SLO, engine, feedback and transport settings stay fixed. No frozen source
or prior audit was edited. V1 and career documents remain unchanged.

Implemented: guarded_recovery_plan.py with deterministic traces, frozen-proposal
validation, conservative initial gate, lossless phase accounting and explicit
action attribution. Eight new synthetic tests plus24 existing held-out tests
passed locally (32 in1.574s). These are logic tests, not simulated vLLM outcomes.
The preview always reports gpu_launch_allowed=false and has no execute option.

Still required: dedicated260s raw-case analysis, shifted recovery/telemetry
checks, paired verdict, runner and independent batch audit; tests for their
integration; raw old-evidence/source review and final protocol/source/trace
freeze. Existing240s analyzers are deliberately not patched or reused by
relabeling timestamps. No cloud connection or GPU work was performed in this
CPU preparation turn. The next safe step is that integration, not renting or
starting another instance yet.
