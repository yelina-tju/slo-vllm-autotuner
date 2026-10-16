# Reviewed recovery continuation — 2026-09-21

User explicitly requested continuation after the failed attempt was reviewed.
This is a new bounded execution linked to the preserved failed attempt, not an
automatic retry or a rewritten successful original batch.

Only four cases, in order:309 adaptive,310 adaptive,310 HIGH48,310 LOW24.
Never rerun309 LOW/HIGH. Require the exact pinned attempt1 report/manifest hashes,
full independent audit of its two completed cases and empty failed case directory.
Reuse the SAVED seed309/310 traces, not newly chosen seeds or workloads.

All original RECOVERY_PROTOCOL.md measurement/acceptance rules remain unchanged.
The only changed pre-existing executed Python files are owned_backend.py (reviewed
SO_REUSEADDR preflight, exact hash pinned) and run_recovery.py (explicit case-list,
linked manifest/verdict and four-case timeout plumbing). All other previously
executed files must hash-identically, including feedback, driver, transport,
cohorts, recovery plan and analysis. New continuation/audit/tests are separately
hashed. No SO_REUSEPORT, arbitrary process kill or automatic retries.

Same port8031, same fresh engine/warmups and per-case600s cap. New batch cap2600s
plus owned cleanup. At most four cases; any execution/accounting/telemetry error
halts remaining cases without retry. New exclusive output directory; original
failed attempt is read-only. New checkpoints contain new cases only; final
verdict combines the independently validated prefix with the four new cases.

Preview audits the prefix and emits the exact plan without GPU imports. Execution
requires --execute plus matching model config, SLO and V1 dependency hashes.
Independent linked audit must validate both source snapshots, all six records,
both sets of checkpoints, trace hashes and declared source changes. Acceptance
thresholds cannot be changed based on new results. Preserve temporal-interruption
limitations when reporting paired differences. No follow-on GPU work auto-starts.
