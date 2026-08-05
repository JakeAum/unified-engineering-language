# The core protocol — how the shell talks to the opaque core

*Spec §3.2: every analysis has a uniform shell and an opaque core. The shell never
scales with cost; a 100 ms script and a 10-hour CFD campaign are the same shape of
thing. This protocol is that shape, for local execution of **Python cores**.*

*v0.2 note (ADR-0005): `core expr` and `core stub` bodies do NOT use this
protocol — they are parsed, type-checked, and evaluated by the kernel itself
(interval arithmetic in canonical SI, no subprocess), and their canonical text
is their content hash. This document governs the opaque kind only.*

A core is an executable script (Python, run with the project root as cwd).
Verification probes (v0.3, ADR-0008) re-invoke the same script with perturbed
or golden-case inputs through this same protocol; probes rewrite the `si`
field (and scalar `value`) of the targeted inputs, so cores should read `si` —
the protocol's recommendation since v0.1.
The scheduler sends one JSON object on **stdin** and expects one JSON object on
**stdout**. Exit code 0 with valid JSON is success; anything else marks the node
`failed` (UEL0703) with stderr's tail in the diagnostic.

## stdin

```json
{
  "node": "SparStaticLimit",
  "kind": "analysis",                  // or "geometry"
  "seed": 0,                           // pinned (spec §4.3); use for ALL randomness
  "inputs": {                          // resolved knowns
    "load":  {"value": 12.0, "unit": "kN", "si": 12000.0},
    "section_Ixx": {"value": 8930.2, "unit": "mm^4", "si": 8.9302e-09,
                     "unc": {"kind": "rel", "value": 0.02}}
  },
  "params": {                          // literal node-local quantities, same shape
    "outer_diameter": {"value": 22.0, "unit": "mm", "si": 0.022}
  },
  "outputs_declared": {                // what the shell expects back
    "FoS": {"unit": "", "artifact": false},
    "max_deflection": {"unit": "mm", "artifact": false}
  }
}
```

`si` is the value converted to SI-coherent units (affine handled); intervals come
as two-element arrays in both `value` and `si`.

## stdout

```json
{
  "outputs": {
    "FoS": {"value": 1.92, "unit": "", "unc": {"kind": "abs", "value": 0.12}},
    "max_deflection": {"value": 6.1, "unit": "mm"},
    "mesh": {"artifact": "out/spar.msh"}        // for declared artifact outputs
  },
  "features": {                                  // geometry feature claims (DFM)
    "min_wall_thickness": {"value": 1.6, "unit": "mm"},
    "sharp_internal_corner_count": {"value": 0}
  },
  "assertions": [                                // MANDATORY for geometry nodes
    {"name": "tube_has_two_circular_faces", "passed": true},
    {"name": "wall_positive", "passed": true, "detail": "wall = 1.6 mm"}
  ],
  "convergence": {"residual": 3.1e-06},          // metrics: persisted to run.convergence;
                                                 // `verify converged <m> <= t` binds them (v0.6)
  "notes": "free text, recorded"
}
```

Rules enforced by the shell:

- Every declared non-artifact output must come back with a unit of the declared
  **dimension** (any scale — the shell normalizes into the declared unit; UEL0704).
- Undeclared outputs are ignored with a warning — undeclared values cannot carry
  staleness, so nothing may consume them.
- **Geometry cores must return at least one assertion** (UEL0601) and every
  assertion must pass (UEL0602): late-binding selectors silently grabbing
  different topology after regeneration is code-CAD's classic failure, and it is
  a compile-visible failure here, not a silently wrong part.
- `features` are open-vocabulary claims about shape, checked against the bound
  process's DFM ruleset (spec §7.1). Feature values land in the lock and are
  re-checked at compile time from then on.
- `convergence` metrics (finite numbers only) persist into the lock's
  `run.convergence`. If the analysis declares `verify converged <metric> <= t`,
  the metric must be present and under `t` right after the run — a missing
  metric is a failed run (silence is not convergence), an over-threshold one
  is UEL0808 (v0.6, ADR-0009).
- Determinism: any stochastic step must derive from `seed`. Two runs of the same
  recipe should produce equal-within-tolerance outputs; the tolerance policy
  (`[tolerances]` in uel.toml) absorbs float noise below the declared grid.
- Non-finite outputs (NaN/Inf) are rejected (UEL0704): a diverged solve is a
  failed run, not a value.

## Trust model

`uel build` executes project code — cores run with the invoker's privileges,
exactly like `make` or `cargo build` running build scripts. Check out models
only from sources you would run a build for. `uel check` never executes cores
(compile time never opens them, spec §3.2). The lock is a local cache with the
same trust standing as any build cache: tampering with it can misreport
freshness until the next build, never alter checked semantics.
