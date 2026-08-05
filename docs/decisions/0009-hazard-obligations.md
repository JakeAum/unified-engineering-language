# ADR-0009 — Hazard obligations, sensitivity, convergence: the recursive-detail harness

*Status: accepted · v0.6 · 2026-08-05 · extends spec §2.5 (envelopes/claims) and §3.1 (framing)*

## Intent

The program owner's directive, arriving as a meme that is really a checklist:
topology optimization "fails" not because the algorithms are bad but because a
single-parameter stiffness game was treated as engineering — one static load
case, von Mises on a material whose ductility nobody checked, lateral-torsional
buckling absent from a load case it would dominate (critical moment falling
with the **cube** of flange thickness and the **square** of unbraced length), a
mesh too coarse to see the stress risers, no thought for fixturing, and no
re-check when Dave moved the bolt pattern a quarter inch. *"The devil is in the
details at every single layer."*

UEL already re-checks Dave's bolt pattern (staleness cones), already carries
fixturing knowledge (DFM rulesets), already computes acceptance (targets). The
remaining gap is structural: **the solver answers the question you asked; no
part of the system asks the questions you didn't.** Every model in a framing is
blind to specific physics — and that blindness is *knowledge about the model*,
stable across projects, exactly the kind of content a language should ship.

## Decision

**1. Registered models carry hazard lists.** A new library kind:

    model beam.euler_bernoulli {
      doc "Slender-beam bending: plane sections remain plane, in-plane only."
      hazard lateral_torsional_buckling "the critical moment falls with the cube of
        flange thickness and the square of unbraced length; an in-plane check stays
        green while the compression flange rolls sideways"
      hazard shear_deformation "below span/depth ~10 the model overpredicts stiffness"
    }

A hazard is a *failure mode the model structurally cannot see*, named as a
claim in the taxonomy (typo-checked, UEL0504) with the one-line reason it
kills. `uel/stdlib/models.uel` registers eighteen models across structures,
aero, thermal, RF, power, controls, and tracking — the graybeard's checklist,
attached to the model choice itself so it follows every use.

**2. Using a registered model creates per-hazard obligations.** For each
analysis framed with a registered model, every hazard must be answered:

- **covered** — some analysis carries `covers <hazard>` in its framing: the
  project contains the analysis that actually asks that question. The ground
  station's `VortexShedding` node exists because this check demanded it — the
  bluff-body drag model cannot see periodic lift, so a Strouhal-vs-first-mode
  separation analysis now answers it (separation ≈ 31, computed, with a
  target).
- **waived** — the using framing carries `waive <hazard> because "reason"`.
  The reason is grammatically required: a waiver without a reason is denial.
  The three examples now carry 25 waivers, each an actual engineering
  argument ("closed circular tube: no weak axis and GJ ~ EI — LTB needs an
  open section", "the drag crisis only lowers Cd, so the subcritical value
  bounds the load").
- otherwise **UEL0510** (warning): the model's why-text is put in front of the
  engineer, with the registration site cited. The status projection carries
  the full coverage ledger.

Granularity, honestly: coverage is **project-wide** in v0.6 (any `covers`
discharges the hazard for all users of the model), while waivers are
per-framing. Per-subject binding — *whose* bracket was LTB-checked — needs
instance-scoped claims and is named future work, not silently claimed.
Severity is warning, not error: a new stdlib registration must surface debt in
existing projects without bricking them; teams gate on warnings where they
choose.

**3. Sensitivity is a query, not a study.** `uel query sensitivity <node>`
perturbs each input +5 % (SI) through the same machinery as monotone probes and
prints the elasticity matrix e = %Δoutput / %Δinput. Superlinear inputs
(|e| > 1.05, robust to lock quantization) are flagged ▲ — the cube-law flange
and the V² gust made visible in one command (WindLoads: wind_op e = +2.05 ▲,
every other input exactly 1.00 or dead). Dead inputs (|e| < 0.01) are flagged
too: an input that moves nothing is either insensitive or not actually wired
in, and both are worth knowing.

**4. Convergence is a contract.** The core protocol gains an optional
`convergence` object ({metric: number}), persisted into the lock's run record;
a new contract form binds it:

    verify converged residual <= 1e-6

Checked immediately after the run: metric missing → **failed run** ("silence
is not convergence"); metric above threshold → failed run (UEL0808), evidence
in `run.verify` like every other probe. This is the coarse-mesh killer stated
positively: a result must carry its own discretization/iteration error, under
a declared line. Closed-form cores cannot declare it (UEL0107 — there is no
iteration to converge); the shipped examples' cores are all closed-form, so
the live demonstration is a genuinely iterating Newton solver in the test
suite (`tests/test_hazards.py`), graded in CI both passing and failing — the
same load-bearing-or-dead rule ADR-0008 applied to FMU import.

## Consequences

- The meme's failure ladder now has a mechanical rung each: single load case →
  hazard obligations; unchecked ductility → `structure.von_mises_static`'s
  hazards; LTB → registered on `beam.euler_bernoulli` (and waived on the
  apache-one spar for the honest reason that a closed tube has no weak axis);
  coarse mesh → convergence contracts; cube laws → the sensitivity flag;
  Dave's bolt pattern → the staleness machinery that already existed.
- Schema 0.3 (new node kind `model`, framing `covers`/`waives`, verify kind
  `converged`). All fields omit-empty: untouched analyses keep byte-identical
  encodings, and the full relock under 0.6.0 reproduced every value across
  all three examples.
- The obligation is deliberately *social* at the edges: `covers` is asserted,
  not proven — a claim of coverage is reviewable prose plus an analysis, not
  a formal proof that the analysis is sufficient. The dossier and the ledger
  make it visible; judgment still carries the weight. Declared-but-unchecked
  beats undeclared, again.

## Alternatives rejected

- **Hazards as framing assumptions** (reuse `assume`): an assumption is the
  author volunteering; a hazard is the library obliging. The force must come
  from the model registry, or the engineer who most needs the question never
  hears it.
- **Errors instead of warnings**: would make every stdlib registry addition a
  breaking change for downstream projects — the registry would ossify.
- **Waiver-only (no `covers`)**: pushes projects to write waiver prose where
  the right answer is an analysis; the ground-station VortexShedding node is
  the counterexample the mechanism exists to force.
