# Recovery evaluation design notes — 2026-09-20

Stage12 update: LOW24/HIGH48 now replicated and independently audited; see
COARSE_BRACKET_RESULTS.md. This document remains a design draft, not a frozen
recovery execution protocol. The timing review at the end supersedes assuming
that the original provisional80s high-load phase will be sufficient.

Draft only, prepared while the frozen6/12/18 calibration runs. Do not start this
experiment automatically, change the calibration, or claim a high-pressure rate
has been found before all six runs and offline audit complete.

## Why a normal low-rate start may not test decrease at all

The current controller stops increasing when measured pressure reaches0.8, before
the actual violation threshold1.0. A healthy gradual start can therefore avoid all
breaches. That is desirable, but cannot demonstrate the decrease path on real GPU
pressure. Increasing offered traffic while the gate remains conservatively capped
also does not necessarily overload the backend.

## Conditional design if a replicated low/high pair is found

Use the selected HIGH rate as an explicitly adverse initial admission setting,
not as a claimed production default. Low offered traffic at the beginning can
establish compliant operation; a fixed high-offered phase then exercises the
known high-rate pressure region, followed by a low-offered phase.

Compare three arms on the same trace: fixed selected LOW, fixed selected HIGH,
and adaptive initialized at HIGH. Raise adaptive bounds only in this separately
frozen evaluation configuration; never silently change the existing production
prototype default maximum6 or historical experiments.

A potential phase layout is40/80/40 seconds (160 total), keeping boundaries on
the20s evidence grid. Numeric offered rates, seeds, run order, repeats and bounds
are not frozen here. High offered load should reproduce the calibration condition;
low offered load must actually be low enough for the HIGH static gate to be
compliant. Verify this assumption in the data, rather than infer it solely from
configured RPS. If it fails, retain the failure and do not relabel the phases.

## Outcomes to separate

1. **Detection:** when enough fresh evidence of an actual SLO breach becomes
   available; this differs from the first violated request's timestamp.
2. **Actuation:** acknowledgement time, old/new rate, revision and settling
   deadline; verify the multiplicative decrease and no stale evidence.
3. **Recovery:** subsequent valid full windows meet the SLO while pressure is
   still applied, if enough post-action high-phase time remains. Recovery only
   after offered load subsides cannot by itself be credited to the controller.
4. **Cost:** full-trace compliant goodput, rejected demand, violations and phase
   breakdown. Do not count only the recovered tail or omit initial adverse cost.
5. **Low-load return:** low demand may correctly prevent growth. Recovery of SLO
   is not synonymous with returning the rate to its initial HIGH value.

Compare with both static arms to distinguish a safety/throughput tradeoff from
merely rejecting more requests. Use matched traces and balanced/interleaved order
within a new batch, not only yesterday's static data. State that adversarial
initialization tests recovery behavior, not typical startup performance.

## If expanded calibration is still inconclusive

Do not run a nominal "recovery" experiment with no observed violation region.
Review whether another bounded expansion, a more demanding already-supported
model/workload, or closing this branch with its negative result is the best use
of GPU time. No setting is selected in this draft. Do not tighten the SLO solely
to force a positive result, extrapolate an optimal rate, or continuously add seeds.

## Timing review during stage12 (still not an execution protocol)

Do not freeze the provisional80s high-load phase without checking how many
decreases may be needed. For candidate anchors L < H and multiplicative factor
beta=0.7, the number of ideal decreases needed to reach or pass the tested LOW is
`k = ceil(log(L/H) / log(beta))`, ignoring the configured minimum clamp.
This is an arithmetic rate bound, NOT a guarantee that latency decreases
monotonically or that the system will recover.

Each action consumes a full20s evidence window, outcome-finalization delay and
then20s of settling before fresh evidence. A second required decrease can leave
no fully observed recovered window inside an80s high-load phase. Windows after
the offered load drops cannot establish actuation-caused recovery.

For illustration only, IF24/48 replicates and passes independent audit, the
ideal path is48 -> 33.6 -> 23.52. The provisional high-load phase should then be
reconsidered (e.g.160s) to allow two actions AND at least two full recovered
high-load windows, with timeout/tick delays included in the budget. Freeze the
actual duration, seeds and exact acceptance criteria separately, before GPU
execution. This does not change stage12 or authorize a recovery run.
