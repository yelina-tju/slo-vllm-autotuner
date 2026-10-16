# Before mixed-workload generalization: evidence sample budget

This is a design diagnostic, not a proposed threshold change or GPU result.
The paired alignment experiment deliberately has one balanced request class.
Both algorithms retain a 30-outcome-per-class floor for increasing admission.

If admitted throughput is a, a class occurs with fraction p, and window width
is W, the expected class count under a stationary mixture is approximately:

```text
E[class outcomes] ≈ a * p * W
window for expected count m ≈ m / (a*p)
```

This is not a sufficient-sample guarantee: completion lag, rejections, workload
correlation and randomness all matter. Configured token-bucket rate is NOT a;
use actual admitted throughput rather than the advertised limit.

Illustration using the historical dev201 fixed-mode measured 2.2 admitted RPS,
20s windows, and m=30 (that run was single-class; mixtures below are hypothetical):

| Hypothetical class share | Expected outcomes in 20s | Window for expected count 30 |
|---|---:|---:|
| 100% | 44 | 13.64s |
| 20% | 8.8 | 68.18s |
| 5% | 2.2 | 272.73s |

Thus simply applying the current two-class prototype to an 80/20 mix at a low
initial admitted rate can leave the rare class perpetually under-sampled for
growth. Anchoring windows does not solve this. Treat `insufficient_class_evidence`
as an expected safe hold, not proof that the backend has no capacity.

Before any mixed generalization, explicitly choose and evaluate an evidence
design: longer/class-specific collection horizons, an offline-validated fallback,
or a conservative exploration policy with its own safety protocol. Do not lower
minimum samples just to force positive throughput results. Preserve class-specific
SLOs, absence behavior and timeouts, and report evidence age/sample counts.

No such design is implemented by these notes. No additional GPU run or parameter
change was made for them while the paired alignment batch was running.
