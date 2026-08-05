# Changelog

## v0.1.2 — adoption is a feature (2026-08-05)

The kernel and the loop existed; neither was reachable from any repository but
this one. Program §6.3's adoption-refusal kill criterion is untestable until an
adopter outside this program exists, so adoption became a shipped feature
(ADR-0006):

- **`uel init [path] [--name] [--harness claude|none] [--force]`** — scaffolds
  the project (manifest with tolerances, a starter model that checks clean and
  builds, a core on the JSON protocol, a campaign template, calibration
  directories) and the agent harness at the repo root. `uel init hardware/`
  wires that path through the CI, hooks, and boot docs.
- **The harness**: `AGENTS.md` (vendor-neutral boot context — including what
  the graph guarantees and what it never will) + `CLAUDE.md`; the `uel-loop`
  skill; a **SessionStart hook** that prints the agenda into a waking session;
  a **PostToolUse hook** that runs `uel check` on every `.uel` edit and, on
  errors, exits 2 so the diagnostics land back with the agent that made the
  edit — the merge gate as a keystroke gate; a CI workflow (check, fmt, build,
  lock-is-current); the loop protocol and its cost log.
- **Safety by construction**: existing files are kept unless `--force`;
  `.claude/settings.json` is merged (foreign hooks and permissions preserved,
  idempotent, unparseable JSON left untouched); every harness file is a silent
  no-op when the kernel isn't installed or the edit isn't a model file.
- **The loop, parameterized** — `uel/templates/loop.md.tmpl` is now the
  canonical protocol; `docs/org/user-org-loop.md` is this repo's instance and
  says so; `docs/org/loop-template.md` names the four parameters.
- 17 new unit tests (69 total), including that the scaffolded model is
  formatter-canonical — caught a real defect where a fresh adopter's first CI
  run would have failed its own `uel fmt --check`.

## v0.1.1 — the economics scheduler (2026-08-05)

The substrate schedules cores; nothing scheduled cognition or experiments.
Per the gap analysis (`docs/boot/gap-analysis-v0.1.md`) and ADR-0005:

- **Attention ranking** — `uel stale --rank`: value-orders the stale set
  (failed runs first, then fence pressure, blocked downstream cone,
  requirement linkage; frontier nodes marked buildable-now). Advice, not
  authority: `uel build` still walks in dependency order.
- **Information value** — `uel query info-value [target]`: ranks candidate
  measurements by declared ignorance × consumer cone × fence pressure, so
  contact with the slow oracle goes where it tightens the most. `± cal` and
  declared-TBD rank top; declared-exact ranks nowhere.
- **The agenda** — `uel agenda [--json]`: one surface for a waking agent —
  compile state, ranked stale work, epistemic debt (pending judgments, open
  discrepancies, unreviewed stubs), the next measurement, tightest budgets.
- **Empirical entailment growth** — an output measurement outside its
  predicted band now also emits a reviewable candidate entailment rule
  (`calibration/candidate-rules/`), listing the analysis's declared claims as
  suspects for the dropped physics. Accepted candidates amend `lib.claims`
  through the merge gate, never automatically (ADR-0003 residual doubt 2).
- **Fence-pressure semantics** — exact-zero lower bounds in SI act one-sided
  (a nonnegative quantity cannot exit below zero); affine units keep both
  edges. Pinned in `tests/test_attention.py`.
- **The standing loop** — `docs/org/user-org-loop.md`: the user-org iteration
  protocol (program §7 boundary made operational), run by a scheduled agent
  session; north-star denominators added to program §5.2.
- New conformance kind `agenda/` (2 cases), 11 new unit tests
  (52 tests / 54 cases total).

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
