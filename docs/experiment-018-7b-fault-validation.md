# Experiment 018: Qwen2.5-7B fault and executor validation

## Scope

This stage validates the safety mechanisms with Qwen2.5-7B FP16 on one RTX 4090D. It does not recalibrate policies or tune thresholds. The frozen capacities are 3 RPS for `mixed_80_20` and 12 RPS for `balanced`; canary recovery uses 3 → 6 → 9 → 12 RPS.

The minimum matrix contains eight successful GPU runs:

1. healthy proxy controls: binary and canary (seed 130);
2. persistent first-token delay: binary and canary for seeds 131 and 132;
3. forced `mbt1024 → mbt2048` restart with an in-flight request;
4. the same restart with one target-start failure and automatic source recovery.

CPU-only controller-contract and synthetic HTTP/SSE checks had already passed before these GPU runs.

## Fault-radius metric

For mode \(m\), let \(I_m\) be requests that crossed the fault proxy while injection was active. A request is exposed when it errors, lacks a TTFT observation, or violates either frozen short-request SLO:

$$
E_m = \sum_{r \in I_m}
\mathbf{1}\left[
e_r \lor \operatorname{TTFT}_r > S_{\mathrm{TTFT}}
\lor \operatorname{E2E}_r > S_{\mathrm{E2E}}
\right].
$$

The paired canary reduction is

$$
R_s = \frac{E_{\mathrm{binary},s}-E_{\mathrm{canary},s}}
{E_{\mathrm{binary},s}}.
$$

| Seed | Binary exposure | Canary exposure | Reduction | Binary rollback | Canary rollback |
|---:|---:|---:|---:|---:|---:|
| 131 | 229 | 186 | 18.78% | 20.940 s | 21.041 s |
| 132 | 242 | 186 | 23.14% | 21.051 s | 21.043 s |
| Mean | 235.5 | 186.0 | 21.02% from pooled means | 20.996 s | 21.042 s |

Both paired seeds agree in direction. The mean paired first-rollback delay difference was about +0.047 s. Exposure counts cover the entire persistent-fault episode, including the subsequent configuration rollback and its pause; they do not isolate the causal effect of the first canary stage. Two seeds are mechanism evidence, not enough for a population confidence interval.

## Why every delay run restarted once

The injector intentionally remained active for 60 seconds after the first successful capacity increase. The controller first observed two fresh violating windows and returned to the original 3-RPS `mixed_80_20:selected:mbt1024_fcfs` policy without a server restart. Because the exogenous delay remained active, fresh violations continued even at 3 RPS. The safety controller therefore escalated to `mixed_80_20:rollback:mbt2048_fcfs`, which required a real restart.

This is a two-level safety response rather than an accidental extra restart:

This configuration fallback is distinct from a second canary-stage rollback (9 to 6 RPS). The latter remains covered by CPU contracts, not by these GPU traces. Because the injected delay is external and expires on a fixed clock, the successful restart does not prove that changing the token budget cured the fault.

$$
\text{balanced canary/binary}
\xrightarrow[\approx 21\,s]{\text{confirmed violation}}
\text{mixed selected @ 3 RPS}
\xrightarrow{\text{continued fresh violations}}
\text{mixed rollback @ 3 RPS, mbt2048}.
$$

Gateway audit records show the recovery cooldown blocked renewed capacity increases throughout the remainder. The enhanced auditor now reports the complete rollback chain, final active policy, and whether the chain cascaded into a server restart; it no longer exposes only the first rollback.

## Executor success probe

The successful forced restart observed one in-flight request before switching. A request sent while admission was paused received HTTP 503. The recorded order was:

1. admission paused;
2. in-flight request drained;
3. source stopped;
4. target start command succeeded;
5. target health check passed;
6. four warm-up requests passed;
7. target admission resumed.

The transaction applied `balanced:mbt1024-seq256 → balanced:mbt2048-seq256` in 71.681 s. A real post-recovery completion passed, cleanup stopped the backend, and no GPU process remained.

The first execution of this probe completed the service transaction but failed while writing its report because a `deque` was passed to `json.dumps`. That directory was preserved and not overwritten. The reporting code was corrected to serialize `list(runtime.executions)`, and the successful evidence was written to the explicit `restart_ok_retry1` directory.

## Target-start failure and rollback probe

The target was started once with an intentionally nonexistent model path. Its launch command succeeded, but the health check timed out after the frozen 180-second budget. The executor then:

1. recorded target health failure;
2. stopped the failed target;
3. restarted the original `mbt1024` source;
4. passed source health and four warm-up requests;
5. restored source admission;
6. passed a real post-recovery completion.

The transaction status was `startup_failed_rolled_back`, the final policy equalled the source policy, and total duration was 242.069 s. Cleanup passed and no GPU process remained.

## Independent audit and evidence

`scripts/audit_7b_fault_pair.py` verifies trace/payload identity, proxy records, SLO exposure, rollback chain, terminal admission and control errors. `scripts/audit_7b_restart_probe.py` independently checks in-flight observation, paused-request rejection, required restart, ordered transaction steps, terminal health, post-recovery inference, cleanup and final policy. All checks passed. The cloud test suite also passed 99/99 tests before the executor probes.

Evidence archives copied off the rented instance:

- `fault7b-delay-evidence.tar.gz`: SHA-256 `acdf32357adb528a15bdb4d1a33bb6b53465186e0f7d0fd7bf6e4db1eb74abcf`;
- `fault7b-restart-evidence.tar.gz`: SHA-256 `a1135cb98e949c41d38bd0f2b34583470c30f7d9a80d8451ece2a01263ea11b0`.

## Claim boundary

The experiment supports these claims:

- canary recovery reduced observed fault exposure in both paired 7B traces;
- fresh-evidence confirmation, rollback cooldown and two-level fallback operated on a real HTTP/SSE stream;
- pause, drain, restart, health, warm-up, admission resume and target-start rollback worked with a real 7B backend.

It does not establish a production incident probability, a cross-GPU performance guarantee, or a statistically stable 21% universal reduction. Those would require more independent traces and hardware families.
