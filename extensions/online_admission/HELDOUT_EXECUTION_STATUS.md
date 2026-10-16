# Held-out recovery execution record

Completion update: all six cases finished and are backed up locally. Independent
raw audit passed, but scientific verdict is inconclusive_baseline for both seeds.
See HELDOUT_RESULTS.md for the boundary-overlap diagnosis. GPU is idle; no next
GPU batch has been launched. Launch-time text below is historical.

2026-09-21. Six-case attempt1 launched after independent development audit and
prelaunch CPU/HTTP tests. No held-out outcome is established at launch.

## Immutable execution inputs

- Protocol: recovery-heldout401-402-v1. Seed401 LOW24/HIGH48/adaptive48;
  seed402 adaptive48/HIGH48/LOW24. Each trace240s, offered6/72/6 RPS for40/160/40s.
- Model, engine flags, SLOs, observation, settling, recovery gates and controller
  unchanged from development. All65 executed development Python files match.
- Local source archive: `../work/heldout-v18-source.tar.gz` from repository root.
  SHA256 `a3172bcb02ca92a94e027ad23031ae6259a130a3bace0c821160668e706229b8`.
- Prelaunch freeze: `../work/heldout-v18-local-freeze.json`.
  SHA256 `c776638a7a833b60e96e43c9426f88e3819467cd5438d9a15761b329087f499d`.
- Remote immutable source: `/root/autodl-tmp/heldout-v18/online_admission`.
- Remote output: `/root/autodl-tmp/online-admission-pilot-results/heldout401-402-attempt1`.
- Remote console: `/root/autodl-tmp/heldout-v18-run.log`.

61 relevant local tests passed in6.538s; full cloud extension suite179 tests in
7.102s. These overlap and must not be added. Source/archive and freeze hashes
matched after upload. GPU was idle before launch. Six cases maximum,600s/case,
3900s/batch; no retry, no automatic extra seeds or tuning after outcomes.

## Resume safely

Inspect processes, console, report/checkpoints and GPU before any action. Never
rerun the launch command against this output or create an alternative output to
repeat completed cases. Do not modify the executed snapshot. A failed batch must
remain failed until explicitly reviewed; preserve every valid partial result.

When finished: inspect cleanup and GPU state, run original V1 regressions, archive
source + freeze + raw outputs/log, verify remote/local SHA256 and safe members,
then run audit_heldout.py against the extracted snapshot and both historical
development snapshots. Preserve both execution status and scientific verdict.
Only independent raw audit establishes the final result. Instance shutdown is
not automatic; while traffic is running, shutdown would interrupt the experiment.

## Interpretation fixed before results

The question is recovery replication on unseen traces from the SAME distribution,
not broad generalization or an optimum. LOW/HIGH baselines must reproduce;
otherwise report inconclusive. Adaptive recovery must pass on BOTH seeds before
high load ceases. Report full-trace throughput AND violation/rejection costs,
including adverse initialization. Never report only the recovered tail.
