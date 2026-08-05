# Changelog

## v0.3.0 — zero-trust, operationalized (2026-08-05)

The review posture the program demands: an agent auditing an analysis should
never have to believe its author — and everything needed to audit, including
the wrapper around a black box, should arrive packaged for a context window.

- **Verification contracts** (ADR-0008) — `verify <out> against <ref> within
  tol` (lock-vs-lock cross-check; its natural oracle is a transparent expr
  surrogate — the fidelity ladder's real job), `verify <out> monotone with
  <input> rising|falling` (the kernel perturbs and re-runs the core at build
  time), `verify case "file" within tol` (golden inputs re-proven every
  build). A run that breaks its own contract is a failed run (UEL0808), the
  same principle as geometry's mandatory assertions; unbuilt sides are
  pending (UEL0809); evidence lands in the lock (`run.verify`). The pinned
  test scenario: a core computing k·(50−w)² instead of k·w² agrees exactly
  at the operating point — the cross-check passes, the monotone probe and
  golden case both kill it.
- **Declared wrappers** — `core python "…" { tool "su2" "8.0.1"  interface
  "model.xml" sha256 "…" }`: pinned external tools and the black box's own
  interface manifest (the FMU modelDescription pattern) are identity, hash
  into the recipe, and surface in the dossier.
- **`uel pack <node>`** — the review dossier: one context-sized document
  carrying the claim, the framing fence, every flowing value with
  provenance, the argument itself (expr body verbatim / capped python
  source / interface manifest), contract verdicts, targets, measured
  validations, blast radius, the author's judgment verbatim, and the recipe
  hashes to cite. Upstream nodes are one-liners — pack them separately.
- **The trust ledger** — the status projection now names where belief is
  load-bearing: verified by construction / by contract (with verdicts) /
  trusted on the author's word.
- Applied: the ground station carries live contracts (WindLoads vs a
  first-principles oracle + monotone probe; PedestalModes mode rising with
  stiffness; EnclosureThermal 35 °C golden case). 63 conformance cases,
  54 unit tests.

## v0.2.0 — the compiler sees inside the physics (2026-08-05)

Every feature in this release is a fix for a weakness the v0.1 retrospective
named after building three real projects with the language. Schema 0.2;
hashing epoch bumped (tool pins + level encoding) — all locks re-locked, with
apache-one values reproducing byte-identically and the ground stations to
sub-millidecibel.

- **Level quantities as types** (ADR-0006) — `dB` family units carry their
  reference in the type: `dBW`, `dBm` (additive −30), `dBHz`, `dBK`, `dBi`,
  composition (`dB/K`, `dBW/(K*Hz)`), one arithmetic rule (levels add where
  linear quantities multiply), `db()`/`lin()` conversions, dB-delta
  uncertainty, level-aware hashing (`52 dBm` == `22 dBW`) and tolerance
  grids. The RF blind spot the retrospective named is closed: a link budget's
  `dBHz` is now derived by the checker, not asserted by a naming convention.
- **Expression cores** (ADR-0005) — `core expr { let … ; out = … }`: the
  formula moves into the language. Dimensional/level inference over the whole
  body at check time (UEL0310–0312: unknown names with hyphen-aware hints,
  mixed-scale arithmetic, output-vs-declaration contract); kernel-side
  interval evaluation seeded from the knowns' declared bands (worst-case
  enclosures, documented as such); canonical body text is the content hash;
  `sin`/`cos` with exact interval extrema; physical constants under `const.*`
  (Boltzmann enters link budgets as `db(const.k_B)` exactly, retiring the
  228.6 contract constant). `core stub { … }` promotes the ground-station
  contract-and-stubs org pattern into the language, with a maturity ledger
  (UEL0807 + status projection).
- **Targets and seam values** (ADR-0007) — `outputs { margin_db : dB ± target
  >= req.LNK-002.min_margin_db }` re-verdicted against the lock on every
  build/check (UEL0804 violated = red gate; band-crossing = warning; UEL0805
  pending); fences on output-referencing knowns checked statically for type
  (UEL0505) and against the **value actually flowing** with its band
  (UEL0806, producer cited). Lock-derived verdicts red-gate merges but never
  gate the scheduler. `contains X x N` mints instance designators (BOM,
  `uel query instances`) for per-serial as-built addressing.
- **Migration** — both ground stations' RF/pointing chains are expr cores now
  (ten Python cores deleted); the baseline and the 1/10-cost excursion share
  the identical LinkMargin formula text, hash-provably. The LC margin's
  worst-case band crossing the 3 dB floor is a standing computed warning —
  TRADE.md's declared thinness, now enforced by the checker. Requirements
  state EIRP in `dBW`, G/T in `dB/K`, C/N0 in `dBHz`.
- Conformance grows to 60 cases (expr dimensional catch, level algebra
  derivation, target pending, seam type mismatch, stub ledger, level-unit
  verdicts); 50 unit tests (closed-form physics match, level-rename staleness
  invariance, target/seam re-verdicts, interval arithmetic edge cases).

## v0.1.0 — the kernel proof (2026-08-04)

The spec §11 v0.1 scope, complete and load-bearing, per the program plan's phases:

- **Stage 0** — constitution ratified (spec + program), decision log opened,
  merge-gate CI.
- **Phase 1** — semantic schema frozen for edition 2026 before any syntax;
  canonical byte-stable encoding; conformance skeleton; eleven realistic
  fragments round-tripping.
- **Phase 2** — recursive-descent parser (contextual keywords, hyphenated
  idents), Kennedy-style units engine (SI + engineering vocabulary, affine
  temperature discipline, currency as a base dimension), resolver with binding
  sugar and geometry-output fallthrough, structured diagnostics with stable
  codes/reasons/verbatim fixes, zero-config formatter. Seeded errors converge
  to clean under a mechanical fix driver.
- **Phase 3** — tolerance-quantized SI-normalized content hashing; recipe
  hashes with per-part breakdowns; committed lock with minimal diffs; local
  scheduler over the JSON core protocol with early cutoff; geometry cores must
  assert topology. 50-node demo: exact invalidation cones, both tolerance
  directions.
- **Phase 4** — conservation (domains, directions, effort-window containment,
  net draw vs supply, energy balance), budget rollups with margins, envelope
  composition (boxes + structural-claim entailment with cited rationales), DFM
  rulesets against locked feature claims. R1 de-risk spike discharged 11/11
  (ADR-0003).
- **Phase 5** — calibration loop (overlays, per-serial as-built, tightening,
  discrepancy events, investigation stubs, prediction validation), hash-stamped
  projections (BOM/ICD/travelers/status), provenance query, DOT export.
- **Vertical slice** — `examples/apache-one`: structures→flutter and
  power→thermal chains, COTS datasheets, two applied test campaigns, leverage
  measured and recorded (`docs/boot/leverage-v0.1.md`).
- **Red team round 1** — four findings fixed and pinned (ADR-0004).
