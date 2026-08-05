# ADR-0005 — The economics scheduler: attention ranking, information value, empirical entailment growth

*Status: accepted · post-v0.1 · 2026-08-05 · executes `docs/boot/gap-analysis-v0.1.md` moves 2, 3, 5*

## Intent

The gap analysis (boot library) concluded: inside one iteration the substrate
now costs milliseconds, agent cognition costs context spend, and the physical
oracle costs weeks — so further substrate speedups move nothing, and the next
doubling of leverage must come from managing the two expensive resources.
v0.1 schedules cores; nothing schedules **cognition** (which stale claim
deserves attention first) or **experiments** (which measurement buys the
most). This decision adds both, plus the empirical-growth hook for the
hand-authored entailment web (ADR-0003 residual doubt 2).

## Framing

- Model: transparent linear heuristics over data the graph already carries —
  downstream cones, envelope fences, uncertainty declarations, budget
  rollups. No new syntax, no new node kinds, no solver.
- Boundary: *advice, not authority.* The rankings order attention and
  proposals; the checker still gates, the scheduler still walks in dependency
  order, and taxonomy changes still go through the decision log and the merge
  gate. Nothing here can merge, execute, or amend anything by itself.
- `assume crude_first because "even the crude form beats hand-picking; the
  metric's job is to be wrong in public so calibration can correct it"` —
  sensitivity-aware refinement is the declared v0.2 escalation (spec §4.3
  posture, applied to attention).

## Knowns

Attention score per non-fresh executable (`uel stale --rank`, `uel agenda`):

    score = 8·failed_last_run + 4·fence_pressure + 1·blocked_downstream
          + 2·serves_requirement

Information value per measurable quantity (`uel query info-value`):

    value = declared_ignorance × (1 + consumer_cone) × (1 + fence_pressure)

Definitions, each pinned by conformance (`cases/agenda/`) and unit tests
(`tests/test_attention.py`):

- **fence_pressure** — nearest-edge distance of a band to a fence, normalized
  by fence scale; 1.0 on contact/crossing. An exact-zero lower bound in SI is
  not a real edge (a nonnegative quantity cannot exit below zero), so
  `[0, X]` fences act one-sided; affine units keep both edges because 0 degC
  is 273.15 K.
- **declared_ignorance** — the epistemic component only: relative width of
  `± x` / `± x%`, 1.0 for `± cal` and declared-TBD, 0.0 for declared-exact.
  An interval *value* is an operating range, not ignorance; measuring it
  removes nothing. Info-value therefore ranks *declared* ignorance — it
  cannot see the unmodeled (spec §10.6) and is never sold as covering it.
- **consumer_cone** — direct consumers plus their transitive executable
  descendants: tightening a band many analyses inherit is worth more.
- **frontier** — every upstream fresh: buildable now. Ties break toward
  upstream in topological order, so equal-priority work is offered buildable
  first.

Empirical entailment growth: an output measurement outside its predicted band
(UEL0801) now also emits `calibration/candidate-rules/<target>_<day>.md` — the
analysis's declared structural claims listed as suspects for the dropped
physics, with measurement provenance. Candidates are *reviewable stubs*:
accepted ones amend `lib.claims` through an ADR and the merge gate, never
automatically.

## Derivation

`uel/attention.py` (kernel module), CLI surfaces `uel stale --rank`,
`uel query info-value [target]`, `uel agenda [--json]`; candidate-rule
emission in `uel/calibration.py`. New conformance kind `agenda/` (2 cases:
exact rank order, frontier flags, top measurement; the pressure/cone linear
tradeoff pinned from both sides). 11 unit tests. Demonstrated live on
apache-one: with the W12/W13 campaigns applied, the top-ranked measurement is
`req.STR-014.root_moment` — calibration-pending (`± cal`), inherited by two
analyses, pressing `SparStaticLimit`'s fence at 87 % — which is exactly the
load assumption an engineer would nominate. Gates: 52 unit tests, 54
conformance cases, all green.

## Judgment

Accepted. The weights are declared, not derived; that is the point — they are
public, cheap to amend through this log, and their failures will be visible
in the north-star telemetry (a mis-ranked agenda shows up as agents doing
low-value work; a mis-ranked measurement list shows up as campaigns that
tighten nothing). Doubts, honestly held: (1) fence proximity is a proxy for
risk, not a probability — without distributions, nearest-edge-normalized is
defensible but crude; (2) consumer-cone counting weights all consumers
equally, though some serve requirements and some don't; (3) the zero-lower-
bound rule is a heuristic about physical nonnegativity encoded in SI
coordinates — a fence deliberately excluding small values (e.g. minimum
preload) loses its lower-edge pressure; declare such fences with a nonzero
lo. All three are the sensitivity-aware v0.2 escalation's to fix.

Amendments carried with this decision: spec §11 v0.2 list reordered to put
experiment selection and attention ahead of transport/bridge plumbing;
program §5.2 gains two supporting indicators (cost per merged claim,
information yield per test) so the G2 denominators of the gap analysis are
measured, not asserted.
