# Static endpoint implementation handoff — 2026-09-15

Historical preparation record. Subsequent GPU batch completed and was audited;
see STATIC_ENDPOINTS_RESULTS.md. At preparation time results did not yet exist.
Cloud was reachable and idle at preflight. The previous four adaptive alignment
runs were complete. No old run was repeated and no GPU backend was launched.

## Implemented

- `run_pilot.one_mode('fixed', ...)` accepts config `fixed_rate`, defaulting to
  the historical feedback initial value. The gate uses this independent value;
  feedback configuration is not rewritten. Invalid static rates fail before
  output creation. Adaptive modes retain their original initialization.
- Static metadata records actual initial rate and fixed-grid accounting alignment.
  Static path never invokes Feedback.observe; evidence collection is accounting
  only. Existing adaptive/legacy driver behavior remains covered by regressions.
- Independent audit validates static rate/revision and absence of decisions or
  actuation, along with original request conservation and SLO reconstruction.
- `run_static_endpoints.py` defaults to read-only planning. It audits the reference
  batch and reuses exact saved traces, with hashes checked again before execution.
  `--execute` and explicit source/model/vllm/output arguments are required to run.
- Four-run protocol: seed202 static3/static6, seed203 static6/static3; fresh owned
  engine and identical warmup each time, bounded run/batch, stop on invalid
  accounting or cleanup, no retries. See STATIC_ENDPOINTS_PROTOCOL.md for limits
  and interpretation, particularly cross-batch comparison limitations.

## Checks completed

1. Read-only local CLI planning against the real stage-8 backup passed its full
   independent audit and produced exactly four cases. Seed202 has 1,246 requests;
   seed203 has 1,308. No output directory or GPU process is created by planning.
2. Isolated cloud snapshot CPU/HTTP suite: 64 tests passed, 1.462s. New integration
   coverage confirms static6 with feedback initial3, forbids feedback observation,
   verifies accounting audit and deliberately corrupts the recorded rate to confirm
   rejection. Bad-rate values include zero, negative, bool, NaN, infinity and text.
3. Four additional local stdlib plan tests passed: exact order/read-only behavior,
   trace tampering, out-of-bounds timestamps despite valid hash, failed reference
   audit. These tests were added after the v11 archive; they did not alter runner
   code. Do not describe 68 as one combined suite run.

Local source archive: `../work/static-endpoints-v11-source.tar.gz`.
Remote isolated snapshot: `/root/autodl-tmp/static-endpoints-v11/online_admission`.
Archive SHA256 (verified both ends):
`af031bdec2202c248a0916e47a8ab3433d046db889c47fe1a89a64bd1b62749f`.
The archive precedes the additional four plan tests and this handoff note.

## Resume

First check GPU/process state again. Existing reference remains:
`/root/autodl-tmp/online-admission-pilot-results/alignment-pairs-dev202-203-attempt1`.
Run the default preview before any execution. The intended new result directory
must not already exist; never overwrite or retry blindly. Allow approximately
14–18 minutes for four fresh-engine 180s trials, then audit and back up raw results.
Review these endpoint results before selecting a bounded SLO-pressure experiment.
There are no new GPU performance numbers to add to the resume at this stage.
