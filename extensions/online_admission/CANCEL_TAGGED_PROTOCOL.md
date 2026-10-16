# Tagged cancellation protocol v2 — frozen before the new run

New output and source snapshot; counter-v1 failed results remain unchanged.
Enable vLLM --enable-log-requests. Send unique X-Request-Id tags for the two
timeout requests. Installed completion serving constructs cmpl-<tag>-0; match
exactly one new `Request cmpl-<tag>-0 aborted.` event in the post-start log slice.
Generic abort text, a different ID, or prefix-only matching does not count.

Keep full-length control, two 1.5s deadlines, observed-running, no length finish,
positive token work below 2048, zero running/waiting, >=2s token plateau within
10s, timeout-triggered decrease, local release, health and recovery criteria.
Only replace the non-authoritative aggregate abort-count criterion with the
explicit tagged event; continue recording that counter unchanged as diagnostics.
This is a new protocol, NOT a relabeling of the earlier failed run.

Also sample driver and owned backend processes every second: CPU delta scaled
so 100%=one CPU core; PSS avoids double-counting shared resident pages. Split
startup and probe phases. This is approximate resource characterization of a
small serial fault probe, NOT control-loop-only profiling or load capacity proof.
Read cgroup limits: free/top may show host-wide RAM, not container quota.
Request logging and metric polling add overhead and are not performance settings.

Same bounded lifecycle: 240s startup, 360s whole probe, owned-group cleanup,
new output directory, no automatic retries. No model/backend source patches.
