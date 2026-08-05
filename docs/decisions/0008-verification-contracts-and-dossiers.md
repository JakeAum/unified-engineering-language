# ADR-0008 — Verification contracts and review dossiers: zero-trust, operationalized

*Status: accepted · v0.3 · 2026-08-05 · extends spec §3 (claims) and §9.1 (projections)*

## Intent

The v0.2 retrospective question, sharpened by the program owner: an AI agent
reviewing an analysis should not have to *believe* what it is told — it should
be able to verify from first principles, with the full context of what was run
packaged for its context window. Vertical integration (expr cores) covers
formulas; NASTRAN, CFD campaigns, and vendor FMUs will never be written
vertically. The gap is a **contract layer for instruments** and a **packing
surface for reviewers**.

Trust has three legs. v0.2 built the first; this ADR builds the second and
makes the third citable:

1. **by construction** — expr cores: the formula is the argument, type-checked
   and kernel-evaluated (ADR-0005/0006);
2. **by contract** — opaque cores interrogated behaviorally (this ADR);
3. **by reality** — calibration write-back (spec §8).

## Decision

**Verification contracts.** An analysis may declare machine-checkable reasons
to believe its core, graded by the kernel:

    verify gust_moment against WindLoadsOracle.outputs.gust_moment within 10 %
    verify gust_moment monotone with wind_op rising
    verify case "test/verify_enclosure_hotcase.json" within 1 %

- `against` — a lock-vs-lock cross-check against an independent value (its
  natural oracle: a low-fidelity **expr surrogate**, giving the fidelity
  ladder its real job — the transparent rung falsifies the opaque one).
  Judged at check time; disagreement is a red-gating error (UEL0808), an
  unbuilt side is announced pending (UEL0809).
- `monotone` — at build time, the kernel perturbs the named input (+5 % in
  SI) and re-runs the core; the output must move the declared direction.
  This catches wrong physics that is *numerically correct at the operating
  point* — the class of bug a single cross-check can never see.
- `case` — a golden input file re-run at every build; expected outputs must
  reproduce within tolerance (relative `%`, or absolute in a unit — the
  natural spelling for levels: `within 0.5 dB`).
- A run that breaks its own contract is a **failed run, not a result** — the
  same principle as geometry's mandatory topological assertions (spec §6.2),
  generalized. Evidence lands in the lock (`run.verify`), so verdicts are
  citable and survive to review time.

**Declared wrappers.** What surrounds a black box is identity, not prose:

    core python "analysis/wing_cfd.py" {
      tool "su2" "8.0.1"                 # a different solver is a different artifact
      interface "vendor/model.xml" sha256 "9a41…"   # the box's own definition, hashed
    }

Tool pins and interface manifests (the FMU `modelDescription.xml` pattern)
hash into the recipe and surface in the dossier — the *definition* of the
module is reviewable even when the module is not. Case parameters were
already forced typed (knowns/params); nothing about an external run is
allowed to live in an agent's memory.

**The review dossier.** `uel pack <node>` compiles one node's full epistemic
chain into a single context-window-sized document: the claim and its intent,
the framing fence, every flowing value with provenance, the argument itself
(expr body verbatim; capped python source; the interface manifest), the
verification contracts with their latest verdicts, targets and measured
validations, the blast radius, the author's judgment verbatim, and the recipe
hashes to cite. Upstream nodes appear as one-liners — pack them separately;
bounded by construction.

**The ledger.** The status projection now says where belief is load-bearing:
verified by construction / verified by contract (with verdicts) / **trusted
on the author's word** — naked cores are named, not forbidden. Trust is
scoped, cited, and visible.

## Consequences

- The ground station carries live contracts: WindLoads is cross-checked
  against a one-line first-principles oracle and probed for monotonicity;
  PedestalModes' mode must rise with stiffness; EnclosureThermal re-proves a
  35 °C golden case at every build.
- The unit suite pins the flagship scenario: a core computing `k·(50−w)²`
  instead of `k·w²` agrees exactly at w = 25 — the cross-check passes, and
  the monotone probe and golden case both fail it. Layered defense is the
  point, not redundancy.
- Probes re-execute cores; authors of expensive cores write fewer, cheaper
  contracts (`against` costs nothing at build). That trade is theirs to
  declare — and the ledger shows what they chose.

## Revisit

FMU import (shell generation from `modelDescription.xml`) waits for the first
real FMU — load-bearing or dead (ADR-0002). Property contracts beyond
monotone (conservation at declared ports, convexity, bounded sensitivity) and
`uel pack --depth` for multi-node dossiers are v0.4 questions.
