# ADR-0004 — Red-team round 1: findings and fixes

*Status: accepted · v0.1 close-out · 2026-08-04 · program §2.2 / risk R4*

## Intent

Attack the gate before declaring the kernel proof done: hashing equivalences,
core-protocol edge cases, resolver namespaces, net accounting.

## Findings (all fixed in the same change, pinned by `tests/test_redteam.py`)

1. **NaN/Inf through the core protocol crashed the hasher** (severity: high).
   A core returning `{"value": NaN}` reached canonical encoding, which rejects
   non-finite floats by design — as an uncaught exception mid-build. Now UEL0704:
   a diverged solve is a failed run, not a value.
2. **Component member namespace collisions resolved silently.** A port and a
   quantity with the same name made `comp.member` ambiguous; quantities won by
   iteration order. Now UEL0201 with both declaration sites.
3. **Reserved namespaces could be shadowed.** `component req { }` (or `lib`)
   created plausible-looking references that resolve against the wrong tree.
   Now UEL0201 at declaration.
4. **`contains X x 0`** passed the parser and zeroed rollup contributions.
   Now UEL0107; schema already rejected it, the surface now matches.

Verified non-findings (attacks that failed, behavior pinned where cheap):
unit renames don't invalidate (SI-normalized identity); sub-tolerance noise
doesn't invalidate; duplicate connect edges don't double-count net draw (nets
sum ports, not edges); tampered locks fail toward staleness, never toward
false freshness; core stdout junk / nonzero exits / timeouts land as UEL0703
with stderr context.

## Judgment

The gate holds against this round. Standing residue (spec §10.6, R9): the
entailment web is hand-authored; boundary-flapping at quantization grid edges
is inherent to any grid (deterministic, conservative direction); `uel build`
executes project code by design — trust model documented in
docs/core-protocol.md. The green checkmark is never sold as safety.
