# Deadline-anchored evidence — CPU/HTTP stage, 2026-09-14

## Implemented (opt-in, no GPU result yet)

DeadlineCohorts maintains two distinct streams:

1. **Accounting:** unchanged global arrival grid, all offered requests, rejections,
   completions and timeouts. Each request remains in the bounded primary ledger.
2. **Control evidence:** current epoch starts exactly at the acknowledged
   settling deadline. Only arrivals at/after that deadline with the expected rate
   revision enter this stream. Latency windows retain full width, minimum samples,
   confirmations and timeout rules. No shortened cooling period or reduced sample
   floor is used.

After any actuator acknowledgement (success OR failure), create a new epoch.
Success increments the existing rate revision; failure does not. A separate epoch
ID prevents stale evidence reuse after failed application at the same revision.
Feedback now records the exact acknowledgement timestamp instead of reconstructing
it by subtracting settling time from a floating-point deadline.

Retiring evidence does not remove primary requests. Old completions/timeouts
still update accounting; a late success cannot undo an already-accounted timeout.
Already-returned evidence windows are checked against the current epoch before
use, including after an earlier window in the same tick causes reanchoring.

Transport logs distinguish accounting_only, retired_evidence, and actionable
evidence. Only the latter reaches feedback. Per-request results additionally
record admission revision, epoch and start/end timestamps for future audits.
Accounting and evidence streams intentionally describe some requests twice for
different purposes; they must NOT be summed together as offered traffic.
audit_pilot.py counts only accounting rows when checking request conservation.

## Validation

53 extension tests passed on cloud with frozen-v1 dependencies; 102 frozen v1
tests passed. GPU check 0 MiB / 0%. No model was launched in this stage.

Coverage includes:

- retired request times out and remains in accounting;
- arrivals just before/at the deadline, strict revision separation;
- failed actuation reanchors at the same revision without unpausing admission;
- successful HTTP evidence -> acknowledged update -> exact epoch reanchor;
- original request cap and timestamp validation;
- identical continuous event stream through fixed and anchored implementations.

The deterministic comparison assumes prior applied rate 4 RPS, revision 1,
settling deadline 60.125s, 20s cohorts, >=30 samples, two healthy confirmations,
and identical arrivals every .2s with healthy completed latency. First proposed
increase is at **120s with fixed cohorts vs 100.125s with anchored cohorts**:
19.875s earlier. Proposals are not applied in that comparison. This is a
state-machine timing result under scripted evidence, NOT measured GPU throughput
or a guarantee of the same gain on real traces. Actual cohort membership and
sample counts change with alignment.

## Compatibility and limits

- Existing fixed-grid path stays the default. pilot_config.json was not changed.
- Optional config field `cohort_alignment: "deadline"` selects anchored cohorts
  for the adaptive mode; the fixed-rate mode remains unchanged.
- Frozen source, dev201 results, failed counter probe, and passed tagged probe
  remain untouched. Current implementation is in the independent extension and
  cloud /root/autodl-tmp/online-admission-deadline-v9.
- The two ledgers add metadata/aggregation work; bounded by the original
  max_requests policy, but new CPU/memory overhead has not been profiled.
- Retired/cooldown timeouts remain accounting evidence, not new-epoch control
  triggers. This remains revision-scoped feedback, not a universal watchdog.
- Arbitrary model/lifecycle/class-set changes are still unsupported. Single
  event-loop ownership and serialized actuator/tick access remain required.
- Final drain still prohibits actuation. Partial evidence at trace end is not
  force-promoted; primary accounting must still finalize every offered request.

## Next experimental comparison

Use the same fixed backend, trace, SLOs, bounds, sample floor, confirmations and
cooling settings for **adaptive fixed-grid vs adaptive deadline-anchored** modes.
Control run order and preserve per-mode warmup/state provenance. Keep the earlier
static-3-RPS smoke separate: it does not isolate alignment's contribution.

Before launch, finalize a runner that explicitly names those two modes and a
paired development protocol; validate per-request membership against epoch logs.
Measure first/next action time, eligible sample counts, discarded evidence,
goodput, violations and rejection counts. No performance gain is predeclared.
