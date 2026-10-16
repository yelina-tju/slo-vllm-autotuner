# Paired alignment development protocol — frozen before launch, 2026-09-14

Question: does anchoring control evidence to the actual settling deadline reduce
avoidable decision latency relative to a fixed evidence grid, without losing
requests, using stale data, or increasing SLO violations in this development load?

Four runs, exactly: seed202 adaptive_fixed then adaptive_deadline; seed203
adaptive_deadline then adaptive_fixed. Each gets a freshly started backend and
four identical 64-token warmups. No shared live engine across modes. Both modes
use the same trace/prompt seeds within each pair. No automatic retries; partial
failures preserved and remaining runs stop if accounting/cleanup is invalid.

Model Qwen2.5-1.5B, FP16, single 4090D, batched tokens1024, sequences256, FCFS,
chunked prefill on, prefix caching off, max model length4096, GPU fraction .75.
SLO source frozen configs/workload_profiles.json balanced: 256 prompt /64 output
tokens, TTFT100ms, E2E400ms. Source/config/trace hashes and per-run launch commands
are recorded. Request logging/resource sampler are OFF for both performance runs.

Identical Poisson traffic phases: 60s@6 RPS, 60s@10 RPS, 60s@6 RPS (180s).
Identical feedback: 3 initial, [1,6] bounds, +1 growth, .7 decrease, pressure<.8,
offered>=.9*rate, >=30 outcomes per class, two confirmations, 20s settling,
20s full evidence window, 10s timeout, .25s tick. Only alignment differs.

Accounting acceptance: every trace ID exactly once, no backend failures,
no pending primary cohorts/in-flight requests at end, dispatch lag<=.25s,
owned-process cleanup. SLO violations are measured negative outcomes, NOT an
excuse to drop a run. No actions at or after the traffic deadline. All offered
requests count in primary accounting once; overlapping evidence is NOT added to
request totals. Audit evidence membership by actual request admission time,
revision and evidence epoch; reconstruct per-class counts and P99 ratios.

Record per-request timings/revisions/epochs, window availability/decision data,
exact acknowledgement/settling timestamps, health/warmup and cleanup. Report
per-seed goodput and rejection/violation counts, first/second action times,
applied-rate history, evidence samples, settling/alignment discards and terminal
drain holds. A mode with no second action is censored, not assigned a made-up time.

Bounds: <=180s traffic per run, 240s startup, 480s per owned run, 1800s batch
deadline, followed by bounded cleanup. Estimated about 14–18 minutes under the
previously observed startup times. No changes after batch starts.

Interpretation: two DEVELOPMENT seeds, no robust CI or generalization claim.
Reversing order across two different seeds reduces but cannot identify all order
effects; model state is restarted but OS/compile caches may persist. This is not
comparison against best static capacity, not overload/fault evaluation, and not a
new final resume percentage. Preserve null/negative effects. Inspect both pairs
before choosing any next experiment; do not add seeds based on sign of results.
