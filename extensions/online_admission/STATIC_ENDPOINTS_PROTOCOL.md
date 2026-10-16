# Static endpoint development protocol — 2026-09-15

Prepared for the next GPU batch; preparation and HTTP/CPU tests are not GPU
performance evidence. Driver defaults to read-only planning; --execute is required
to start owned backends. No adaptive experiment is repeated by this protocol.

Four runs: seed202 static3 then static6; seed203 static6 then static3. Reuse the
exact audited stage-8 arrival/prompt traces, not merely the same seed. Verify hashes
before planning and again before each run. Four identical warmups and a fresh
engine per run, unchanged 1.5B model, engine flags and balanced SLO profile.

Static rate is independent of adaptive initial=3. Static mode uses only accounting
windows; Feedback.observe and hot rate updates must never run. Every request must
retain revision0. Metadata records the effective initial rate; audit checks all
control rates/revisions, no decisions/actuations and unchanged final rate.

Bounds: each trace <=180s and <=10,000 requests; each owned run <=480s, startup
<=240s, whole batch <=1800s, bounded owned-process cleanup. No automatic retries.
Occupied GPU/port refuses launch. Invalid accounting, backend failure or cleanup
stops the remaining batch with logs preserved. SLO breaches are negative outcomes,
not grounds to discard an otherwise valid run. No runtime tuning of thresholds.

Report both endpoint results, rejected demand, compliant goodput, violations,
dispatch/admission lag and cleanup. A higher static rate may beat gradual adaptive
growth on a uniformly easy workload; retain that result. Static6 is the prescribed
upper endpoint, NOT the best-static oracle or proven maximum safe capacity.

Comparisons to yesterday's adaptive data are exploratory cross-batch comparisons:
trace/engine equality does not eliminate time-of-day, host contention or cache
effects. A final adaptive-vs-static claim requires a new frozen interleaved design,
selected static baseline and held-out seeds. Do not promote this batch directly
into career materials.

Next pressure gate: distinguish a high rejected arrival rate from actual SLO
pressure on admitted requests. Define a bounded workload perturbation and frozen
SLOs before running it; report whether pressure was actually induced. A scenario
with no breach does not validate decrease/recovery. Model/backend lifecycle remains
fixed throughout a mode; mixed-class evidence starvation remains unresolved.
