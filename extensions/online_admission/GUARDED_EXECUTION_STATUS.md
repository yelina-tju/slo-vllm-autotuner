# Guarded403/404 attempt1: launch record

Completion2026-09-22: six cases independently audited,72,822 offered records,
88 source hashes; both baseline/recovery gates and full-high evidence checks
pass. Raw evidence backed up locally; GPU idle. See GUARDED_RESULTS.md. The launch
record below is historical; do not start this batch again.

2026-09-21. Full Linux CPU/HTTP extension suite214 tests passed in8.368s.
Uploaded source/freeze SHA256 matched the identities in
GUARDED_INTEGRATION_STATUS.md. GPU0MiB/0%, no prior guarded run or output found.
The frozen six-case launch command was then dispatched. Outcomes are pending.

## Exact execution identity

- Source: `/root/autodl-tmp/guarded-v19/online_admission`.
- Freeze: `/root/autodl-tmp/guarded-v19-local-freeze.json`.
- Output: `/root/autodl-tmp/online-admission-pilot-results/guarded403-404-attempt1`.
- Console: `/root/autodl-tmp/guarded-v19-run.log`.
- Local source/freeze backups: sibling work directory, guarded-v19-source.tar.gz
  and guarded-v19-local-freeze.json. No executed Python source changed.
- Served model: Qwen2.5-1.5B-Instruct, one4090D, unchanged engine/controller/SLO.

The runner re-audits original development and401/402 raw evidence before loading
any model, compares the prelaunch freeze, and checks each private backend's port
and GPU ownership. Orders403 low/high/adaptive,404 adaptive/high/low;260s each,
600s/case,3900s/batch. No automatic retries or extra seeds. Preserve all failures.

The test output containing zero requests and synthetic recovery=True came from
fake-backend lifecycle tests. It is not experimental evidence. Actual traffic
counts are12,124 for403 and12,150 for404, repeated across their three arms.

## Resume and finish

Check processes, console, checkpoints, report and GPU before any next action.
Do not repeat the launch command, overwrite output or edit the executed snapshot.
If running, do not shut down the instance. If failed, preserve partial evidence
and inspect the cause without automatic rerun. If complete, inspect all cleanup,
run V1 CPU regressions, archive source/freeze/log/raw outputs, verify remote/local
SHA256 and safe archive members, then independently audit with
audit_guarded_recovery.py against the exact extracted snapshot and predecessor
snapshots. Report execution status separately from the scientific verdict.

The prior401/402 verdict remains inconclusive_baseline. No new success claim,
resume/interview edit, instance deletion or automatic follow-on GPU batch.
