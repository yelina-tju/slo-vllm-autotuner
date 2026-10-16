# Guarded recovery integration: local freeze, no GPU launch

Execution update: Linux CPU/HTTP214 tests passed and the frozen six-case launch
was dispatched. See GUARDED_EXECUTION_STATUS.md for exact paths and resumption
rules. The local-only statements below describe the earlier preparation turn.

2026-09-21. The dedicated260s execution/analysis/audit chain is implemented.
No cloud connection, GPU run, or change to the old401/402 verdict in this turn.

## Implemented

- guarded_protocol.py: six registered403/404 cases; recursively audits actual
  predecessor evidence and requires its inconclusive_baseline verdict to remain
  intact. All76 predecessor executed Python files must match; no controller edits.
- run_guarded_recovery.py: existing owned backend, warmup, fixed/adaptive
  transport;260s traffic,600s/case,3900s/batch. Exclusive output, checkpoints,
  failed-report preservation, no resume/retry. Explicit execute plus matching
  prelaunch freeze and runtime/model/SLO checks required.
- guarded_recovery_analysis.py: independent ledger reconstruction,260s accounting
  including guard,13 grid windows, observed initial finalization before60s,
  high interval60–220s, recovery confirmation before220s, same settling/freshness
  predicates. Telemetry requires220 samples,250s span, maximum3s gap and0.5s scrape.
  Reports fully_high_decrease_observed separately from operational recovery.
- audit_guarded_recovery.py: validates all six raw cases, source hashes, protocol,
  trace identities, warmup/cleanup, checkpoints, model flags and scientific verdict.

Existing240s runners/analyzers and extracted historical evidence remain unchanged.
The new analyzer is separate so no prior timestamp or result is relabeled.

## Verification and limitations

33 guarded tests passed, then96 combined guarded/held-out/development tests
passed locally in6.862s. These counts overlap. Lifecycle tests use fake transport
and backend objects: their printed zero-request/zero-goodput results are synthetic
contract checks, NOT GPU results. Raw phase/telemetry fixtures mock the base ledger
auditor, whose existing regression tests are included separately.

A real local preview re-audited the saved development and held-out evidence,
verified predecessor source preservation and produced
`../work/guarded-v19-local-freeze.json` (path relative to repository root).
Preview status: frozen_no_gpu_started. Proposed trace counts12,124 and12,150,
72,822 total offered records across six cases if eventually executed.

Local handoff artifacts (relative to repository root):
- `../work/guarded-v19-source.tar.gz`: SHA256
  `4ef5825399fe6e067695de02b7598f7b0caf2684d6d8d741f72358a19e171188`.
- `../work/guarded-v19-local-freeze.json`: SHA256
  `ca0fc0a572369180c7fd23915e1ed090e46d33d7d3985952ceffee07bb1c3562`.

Archive excludes Python bytecode. The archived status document predates this
hash annotation; no Python source changed after the freeze.

Remaining before GPU launch: full Linux CPU/HTTP suite against the exact uploaded
snapshot, matching source archive/freeze hashes, current GPU/port idle and absent
new output directory checks. Local tests do not establish Linux HTTP or GPU
performance. Any source fix after this freeze requires a new freeze/snapshot,
not overwriting this one. No existing experiment may be repeated automatically.

## Next operation

When cloud access is next available, upload the dedicated snapshot, run the Linux
CPU/HTTP tests first, and only after success launch the single six-case guarded
batch. Preserve any negative baseline/recovery verdict; do not add seeds or tune.
Afterward independently download/audit results as before. No new GPU outcome is
claimed yet. V1 and career materials remain unchanged.
