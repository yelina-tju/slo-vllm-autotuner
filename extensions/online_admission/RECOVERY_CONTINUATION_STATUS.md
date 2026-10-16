# Stage13 continuation — historical execution record

Update 2026-09-21: download and independent six-case linked audit have now
completed successfully. See RECOVERY_RESULTS.md for verified results and local
backup identity. The pending statements below describe the earlier interruption,
not current status.

2026-09-21. Four remaining GPU cases completed with runner exit0. Neither old
control was repeated. The original failed attempt remains unchanged. Do NOT
describe final linked audit/local backup as complete yet.

## Observed runner results (provisional until raw-evidence linked audit)

| Seed | Arm | Scheduled goodput req/s | Successful200 | Service violations | Rejected429 |
|---|---|---:|---:|---:|---:|
| 309 | fixed24 (previously audited) | 17.9458 | 4308 | 1 | 7481 |
| 309 | fixed48 (previously audited) | 4.1417 | 8153 | 7118 | 3636 |
| 309 | adaptive (new) | 21.8875 | 6143 | 880 | 5646 |
| 310 | adaptive (new) | 22.3125 | 6199 | 834 | 5800 |
| 310 | fixed48 (new) | 6.3750 | 8208 | 6581 | 3791 |
| 310 | fixed24 (new) | 18.1792 | 4363 | 0 | 7636 |

Each240s with40/160/40s offered6/72/6 RPS. Service-compliant counts and scheduled
goodput differ because scheduled scoring adds recorded driver lag. No new case
reported backend failures, lost trace records or unfinished cohorts.

Both adaptive run-time analyses report recovery under the frozen criterion:

- Seed309: one48->33.6 decrease at60.4296s; two fresh healthy windows confirmed
  at120.8418s,80.8418s after high load begins.
- Seed310: one48->33.6 decrease at60.4257s; confirmation at120.8616s,
  80.8616s after high load begins.
- High offered load persists until200s, so these reported confirmations precede
  offered-load relief. The independent linked audit must still reconstruct this.

The throughput gain relative to fixed24 comes with MORE initial service
violations (880 versus1;834 versus0). This is adverse-initialization recovery,
not proof that adaptive is uniformly safer or better than conservative admission.
No formal stability/optimality or broad generalization claim. Seed309 pairing
crosses the preserved interruption; the combined experiment was not uninterrupted.

## Verified operations and remaining blocker

- Frozen v17 prelaunch CPU/HTTP suite:150 tests passed in4.996s.
- Separate local linked audit/planning/evidence suite:39 tests passed in4.955s;
  these overlap earlier tests and must not be added as distinct totals.
- After completion, frozen V1:102 tests passed in0.157s. GPU0MiB/0%, no compute
  process or experiment runner remained. No instance shutdown/deletion performed.
- Cloud evidence archive was created successfully:
  `/root/autodl-tmp/recovery-continuation-sep21-evidence.tar.gz`
  SHA256 `3c852e87dfd3db788ca31bd23a236600c145830ae63270ade82830d174cd588c`.
- Download was NOT executed: automatic approval review failed because its usage
  limit was reached. This was not a security denial or an experimental failure.
  No alternate transfer method was used to bypass the approval check.
- Thus new raw evidence is still cloud-only. The instance may be shut down, but
  MUST NOT be deleted/released until the new archive is downloaded and verified.

Local frozen source archive `work/recovery-v17-source.tar.gz` (relative to repo
parent) matches cloud SHA256:
`0d2fe765dbeb311ce2b28cd3c84dd4fba57ea896932391c28b7933f96ff42177`.
The new independent auditor was prepared locally while v17 ran; it was not part
of the execution snapshot. Auditor SHA256 at preparation:
`3acd409e6c8e9c073106078041e51bd0aa0e0d0e390859c2d85387cf4ea9f235`.

## Exact safe continuation after approval availability is restored

1. Do not launch or repeat GPU cases. Download the existing cloud archive to
   `work/recovery-continuation-sep21-evidence.tar.gz`.
2. Match the SHA256 above, validate archive member paths/types and extract into
   a new `work/recovery-continuation-sep21-evidence/` directory.
3. Run the linked auditor with BOTH snapshots and the old calibration:

```sh
python extensions/online_admission/audit_recovery_continuation.py \
  ../work/recovery-continuation-sep21-evidence/online-admission-pilot-results/recovery-dev309-310-continuation1 \
  --snapshot ../work/recovery-continuation-sep21-evidence/recovery-v17/online_admission \
  --prefix ../work/recovery-sep21-attempt1-evidence/online-admission-pilot-results/recovery-dev309-310-attempt1 \
  --prefix-snapshot ../work/recovery-sep21-attempt1-evidence/recovery-v15/online_admission \
  --calibration ../work/coarse-bracket-sep20-evidence/online-admission-pilot-results/coarse-dev307-308-attempt1 \
  --output ../work/recovery-continuation-sep21-audit.json
```

4. Run recovery_diagnostics.py on the new result folder for exact action timings
   and generation metrics; keep the old two-case diagnostic separate.
5. Inspect final baseline/recovery verdict and costs before writing a final
   results report or starting any next GPU evaluation. Keep V1/career material
   unchanged until this evidence gate is complete.

The user's next-stage request is being advanced through CPU-only held-out
planning. It does not waive this missing-backup/audit gate.
