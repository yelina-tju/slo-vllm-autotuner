# Stage 9: static endpoint GPU results — 2026-09-15

## Outcome

All four preregistered development runs completed, without retries or extra
parameter trials. Independent local audit passed all 5,108 offered-request records.
Fixed6 produced greater compliant goodput than fixed3 in both seeds. Historical
deadline-anchored adaptive runs fall between the two static endpoints; the current
scenario does NOT demonstrate that adaptation beats a suitable static setting.

No observed backend failures or completed-request SLO violations occurred. All
static controls retained revision0 and their configured rate, with no decisions
or actuation. No pending requests/cohorts remained at completion.

## Complete results

Same Qwen2.5-1.5B, FP16, single 4090D, balanced 256-input/64-output requests,
TTFT100ms/E2E400ms. Each run lasted 180s, with a fresh owned backend and four
identical warmups. Seed202 ran static3 then static6; seed203 reversed the order.
Arrival and prompt traces were reused byte-equivalently as parsed JSON, with
their original hashes verified, rather than regenerated from seeds alone.

| Seed | Mode | Offered | Compliant | Rejected429 | Goodput req/s | P99 TTFT ms | P99 E2E ms |
|---|---|---:|---:|---:|---:|---:|---:|
| 202 | static3 | 1246 | 377 | 869 | 2.0944 | 27.18 | 339.75 |
| 202 | static6 | 1246 | 719 | 527 | 3.9944 | 45.56 | 377.44 |
| 203 | static6 | 1308 | 722 | 586 | 4.0111 | 43.64 | 364.31 |
| 203 | static3 | 1308 | 373 | 935 | 2.0722 | 27.73 | 325.23 |

P99 values are nearest-rank whole-run service latencies over admitted successes;
they are not the controller's per-window ratios. Goodput includes both latency
constraints and the original scheduled-arrival adjustment. An additional scoring
check using actual admission timestamps produced the same compliant counts.
Maximum actual admission lag across the runs was approximately 8.181ms.

The two static6 E2E P99s use approximately 91–94% of the 400ms budget. This is not
large safety headroom. They exceed the controller's 80% growth threshold, though
whole-run quantiles alone cannot determine every historical window decision.

## Comparison with the historical adaptive development runs

| Seed | Static3, this batch | Anchored adaptive, previous batch | Static6, this batch |
|---|---:|---:|---:|
| 202 compliant count | 377 | 508 | 719 |
| 203 compliant count | 373 | 505 | 722 |
| Total compliant count | 750 | 1013 | 1441 |

Each column represents 360 total traffic seconds. The adaptive column has 428
fewer compliant requests than static6, a descriptive difference of -29.7016%.
This is EXPLORATORY CROSS-BATCH evidence, not an unbiased causal estimate of the
cost of safety mechanisms: host contention, runtime timing and cache/clock state
can differ. No confidence interval or held-out generalization claim is made.

The earlier +6.5195% comparison remains valid within its stated scope: anchored
adaptive versus fixed-grid adaptive. That improvement must not be relabeled as
adaptive versus static. These are different questions with different baselines.

Interpretation: gradual admission growth from3 incurs an opportunity cost when6
already meets the tested workload's SLO. Adaptation needs to justify that cost
under changing safe capacity or real SLO pressure, not merely beat a conservative
initial-rate baseline. Static6 is an endpoint, NOT a best-static oracle or proven
maximum safe capacity. No overload-triggered decrease was tested in this batch.

## Independent checks and additional CPU work

- Reconstructed each static run's request membership, unique trace IDs, statuses,
  goodput, window quantiles, unchanged rate/revision, and absence of actuation.
- Matched saved per-run summaries/audits to independently reconstructed results;
  verified exact case order, durations, configuration, profiles, warmups and cleanup.
- Verified all 33 executed Python source hashes and unchanged frozen-v1 dependency
  hashes. Compared model-config hashes and complete engine commands with the
  reference batch, allowing only the private service port to differ.
- Read-only ideal token-bucket replay at scheduled arrival times predicted exactly
  the observed TOTAL admissions in all four cases:377/719/722/373. This does not
  assert per-request identity or prove backend capacity; actual scheduling jitter
  can alter admission outcomes. The replay has no latency/SLO model.
- Five new offline tests passed: command normalization permits only a port change,
  malformed commands fail, one-token refill behavior, fractional token capacity,
  and invalid inputs. Four planning tests and six existing independent-audit tests
  were also rerun and passed locally. Prelaunch cloud suite was64 tests as recorded
  in STATIC_ENDPOINTS_PREPARATION.md; no new combined-suite count is claimed.
- Local audit/replay/tests and pressure-design draft were added while the frozen
  remote v11 batch ran. Running source/configs were not modified. No v1 or career
  materials were changed.

## Evidence and shutdown

Local paths relative to the repository parent:

```text
work/static-endpoints-sep15-evidence.tar.gz
work/static-endpoints-sep15-evidence/static-endpoints-v11/online_admission/
work/static-endpoints-sep15-evidence/online-admission-pilot-results/
    static-endpoints-dev202-203-attempt1/
work/static-endpoints-sep15-audit.json
```

Archive SHA256, matching both local and remote copies:
`ab70d76266d7ae9dd693b1ba08e7e7aabf6ad7a54a077d9e6231c7664c7e9f14`.

143 archive members were checked for safe paths and ordinary file/directory types
before extraction to a new local directory. Remote originals were retained. Final
GPU compute-process query was empty; no static runner or vLLM serve process remained.
No further GPU experiment was launched. The instance may be shut down, but later
pressure experiments still need a GPU; this is not a recommendation to delete it.

## Next gate

Freeze a SMALL bounded pressure calibration after reviewing these results. Given
the measured E2E tail near the SLO, do not leap to a large concurrency/rate without
a budget and stop rule. Verify a low-load compliant region and a higher-load
breaching region with driver health checks; then use a separate frozen
low/high/low trial to test decrease and recovery. See
SLO_PRESSURE_CALIBRATION_DRAFT.md. Numerical calibration settings are not yet
frozen and that draft is not executable. Mixed-class and held-out evaluation
remain later gates. No new resume performance percentage is justified yet.
