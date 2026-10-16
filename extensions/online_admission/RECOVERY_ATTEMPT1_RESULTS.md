# Stage13 recovery attempt1 — interrupted, 2026-09-21

## Status: FAILED batch; two completed controls verified; recovery NOT EVALUATED

The six-case protocol was frozen and126 CPU/HTTP tests passed before launch.
Seed309 LOW24 and HIGH48 completed; starting seed309 adaptive then raised
`OSError(98, 'Address already in use')` at the port8031 preflight in OwnedBackend.
Per the no-retry rule, the batch stopped. No adaptive model process or traffic
was started: that case directory is empty. There is no recovery verdict and no
adaptive performance result. Preserve the original failed report unchanged.

## Completed controls (same11,789-request trace,240s each)

| Arm | Successful200 | Service-compliant | Violations | Rejected429 | Whole scheduled goodput | High-phase scheduled goodput |
|---|---:|---:|---:|---:|---:|---:|
| fixed24 | 4308 | 4307 | 1 | 7481 | 17.9458 | 24.01875 |
| fixed48 | 8153 | 1035 | 7118 | 3636 | 4.1417 | 3.31250 |

Rates are requests/second. Whole-run denominators are240s; high-phase160s.
23,578 offered records were accounted for, with zero backend failures or static
actuation. Every LOW high-phase window was healthy; every HIGH high-phase window
breached. Both initial low-traffic phases were healthy. Thus the seed309 baseline
conditions reproduced; this does not prove seed310 conditions or adaptive recovery.

High-phase LOW violation fraction was1/3844 (0.026%); HIGH was7118/7689 (92.57%).
Both arms' final low-offered phase had223/223 compliant requests without any
policy action. This illustrates why recovery after offered load drops is NOT
evidence of controller benefit. Whole-run actual-admission-timestamp goodput is
17.9458/4.0125; the latter is stricter than the driver's recorded-lag4.1417 score.

465 within-traffic telemetry samples; maximum scrape66.166ms, below500ms.
Supplementary generation metrics have monotone counts and aggregate output64
tokens/sample; final counters lag expected completions+warmups by0 and4.
These are diagnostics, not new acceptance rules or per-request token proof.

## Failure investigation and scoped repair

- The traceback stopped at the advisory socket.bind check, before backend
  directory creation/Popen. Prior HIGH cleanup reported stopped=true, exit0;
  logs show normal API/engine shutdown. GPU query after failure showed0MiB/0%
  with no compute or experiment process.
- `ss`/`netstat`/`lsof` were unavailable. A subsequent /proc/net/tcp and tcp6
  read found no8031 entry. The exact state at the failure instant was NOT saved.
- An isolated Linux loopback-only CPU test reproduces a plausible mechanism:
  server active-close produces TIME_WAIT; the old bare bind raises EADDRINUSE
  despite no live listener. A SO_REUSEADDR probe succeeds in that condition.
  A second test confirms a live listener still causes EADDRINUSE. No SO_REUSEPORT,
  arbitrary process kill, retry loop or GPU execution was introduced.
- Local owned_backend.py now uses check_private_port with SO_REUSEADDR. This is
  still advisory and does not eliminate bind races. Do not label TIME_WAIT as
  definitively proven for this particular failure; transient live occupancy is
  not excluded by later checks. The executed v15 source remains unchanged.

## Verification and preservation

Prelaunch frozen v15:126 tests passed in3.234s. Separate Linux port reproduction:
two tests passed. Frozen original V1 after interruption:102 passed in0.167s.
Local recovery/audit/evidence/timing suite:27 tests passed in2.817s. Counts overlap
with earlier suites and are not additive distinct-test totals.

After preservation, the separate full `recovery-v16-review` snapshot passed145
CPU/HTTP tests in4.898s, including explicit EADDRINUSE assertions for TIME_WAIT
and a live listener. No GPU experiment was launched from that snapshot; the final
GPU compute-process query remained empty. Review-source archive is
`work/recovery-v16-review-source.tar.gz`, SHA256 matching cloud/local:
`adf76dda734bc34d3b20f8f8d05414700024ed4ad685cf024d06bb5a89dff781`.
The earlier evidence archive includes the first two-test port reproduction;
the later review archive also includes stronger errno checks and all local audit
tools. Both are retained separately from the immutable executed v15 snapshot.

Independent partial audit explicitly opted in to reviewing this known prelaunch
failure; the normal auditor rejects failed batches. It verifies the completed
prefix, both checkpoints, exact empty next-case directory, raw requests/windows,
source/config/SLO/model/engine provenance and cleanup. All56 executed Python
hashes match. Result is `completed_prefix_verified`, batch remains `failed`,
verdict remains `not_evaluated_incomplete_batch`. No failed observation is hidden.

Local paths relative to the repository parent:

```text
work/recovery-v15-source.tar.gz
work/recovery-sep21-attempt1-evidence.tar.gz
work/recovery-sep21-attempt1-evidence/recovery-v15/online_admission/
work/recovery-sep21-attempt1-evidence/online-admission-pilot-results/
    recovery-dev309-310-attempt1/
work/recovery-sep21-attempt1-evidence/recovery-portfix-review/
work/recovery-sep21-attempt1-audit.json
work/recovery-sep21-attempt1-diagnostics.json
```

Source archive SHA256:
`87668f51f14219ec54bcd3726197febddf305b2167646d9327453fbac31da7c0`.

Evidence archive SHA256 matching cloud/local:
`8f42d36a89e91e240d3e31cee2e3d147a32a558add4cfc57eedd3ec10f2839ac`.
131 member paths/types checked before extraction into a new local directory.
Cloud originals remain intact; nothing was deleted or shut down automatically.

Read-only partial audit:

```sh
python extensions/online_admission/audit_recovery.py \
  ../work/recovery-sep21-attempt1-evidence/online-admission-pilot-results/recovery-dev309-310-attempt1 \
  --snapshot ../work/recovery-sep21-attempt1-evidence/recovery-v15/online_admission \
  --calibration ../work/coarse-bracket-sep20-evidence/online-admission-pilot-results/coarse-dev307-308-attempt1 \
  --allow-partial
```

## Continuation gate — no new GPU run launched

Remaining order ONLY: seed309 adaptive, seed310 adaptive, seed310 HIGH48,
seed310 LOW24. Preserve exact saved seed309/310 traces, model, phases, SLO and
feedback settings. Do not repeat seed309 LOW/HIGH or silently reuse the failed
output directory. Implement an explicitly reviewed continuation into a new output
directory referencing this archive/report hashes and verify both snapshots.
Record the preflight-only code difference and the interruption as a limitation
of temporal pairing; no claim of an uninterrupted six-case batch.

Before launch: use the now-reviewed preflight/145-test snapshot, verify
the saved prefix, freeze a continuation manifest and prove the completed cases
are skipped. No automatic resume/retry was executed in this turn. After the four
remaining cases, audit the linked six-case evidence before claiming recovery.
GPU is idle and the instance can be shut down between stages. Resume/interview
materials and original V1 are unchanged.
