# ADR-0003 — R1 de-risk spike: the draft envelope formalism holds

*Status: accepted · Phase 4 entry · 2026-08-04 · discharges program §8 R1 trigger*

## Intent

Answer the program's foremost research risk before building Phase 4 on top of it
(program §8.1): *does the draft envelope formalism — box value-predicates plus a
declared structural-claim taxonomy with hand-authored entailments — fit real
cross-domain analysis pairs?* Kill criterion: fewer than half fit → halt Phase 4
and rework foundations.

## Framing

- Model: encode N real cross-domain pairs; grade each on whether the formalism can
  (a) express both sides and (b) produce the physically right verdict — a correct
  *clean* composition counts exactly as much as a correct *rejection*.
- Boundary: Draft 0.1 formalism only (spec §2.5). No SMT beyond box containment;
  entailment closure + pairwise exclusion for structural claims.
- Assumption: `pairs_representative` — because the set spans structures,
  aeroelasticity, aero fidelity ladders, thermal, electronics, propulsion,
  mechanisms, procurement/COTS, and materials, i.e. the couplings the testbed
  vehicle actually exhibits.

## Knowns

`conformance/cases/derisk/p01…p11` (executable; graded in CI by the merge gate):

| # | Pair (producer → consumer) | Expected verdict | Mechanism |
|---|---|---|---|
| 1 | rigid spar static → wing flutter | reject | claim conflict: rigid ⇒ ¬elastic_modes |
| 2 | modal spar → wing flutter | clean | claim provided |
| 3 | incompressible panel → transonic trim | reject | Mach box not covered |
| 4 | lumped ESC thermal → FET placement | reject | lumped ⇒ ¬internal_gradients |
| 5 | static spar → gust response | reject | static ⇒ ¬transient |
| 6 | steady-state prop deck → bus surge | reject | steady_state ⇒ ¬transient |
| 7 | frictionless hinge → actuator heating | reject | frictionless ⇒ ¬joint_heating |
| 8 | 6S battery → COTS regulator (17 V abs max) | reject | effort-window containment |
| 9 | duct cooling → ESC derating | clean | box covered |
| 10 | 120 °C bond fence on 110 °C epoxy | warn | material service limit |
| 11 | 21 kN load → analysis fenced to 18 kN | reject | static input outside own fence |

## Derivation

All eleven encode; all eleven produce the physically right verdict
(`conformance: derisk 11/11`). Fit rate 11/11 against a ≥50% threshold.

## Judgment

R1 trigger does not fire; Phase 4 proceeds on the draft formalism. Honestly held
residual doubts: (1) box predicates cannot express *correlated* validity regions
(e.g. valid iff Mach·sqrt(1−M²) bounded) — deferred to the SMT lowering, v0.2;
(2) the entailment web is hand-authored and will miss cross-domain implications
nobody wrote down — that is spec §10.6 (the unmodeled), mitigated but not solved;
(3) requires-silence is a warning, not an error, by the declared-but-unchecked
principle — watch the issue channel for cases where silence hid a real conflict.
