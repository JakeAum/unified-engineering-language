# Changelog

## Unreleased — the exoskeleton pass

Positions UEL as a harness-agnostic tool that agentic harnesses call, rather
than a harness of its own: the fast mechanical oracle, the way `rustc` and
`cargo test` are what made coding agents good at Rust. Substance portable,
reflexes local. Also reconciles the v0.1.x branch's work onto the v0.6 kernel,
retiring the fork.

### The tool surface is an API (`docs/stability.md`)

- **A written stability contract.** Diagnostic-code identity, exit-code
  semantics and the JSON envelope are frozen; subcommands, result fields and
  the code set are additive-only; message prose and rendered output are
  explicitly unstable so the fix-loop product surface stays free to improve.
  Callers match on `code`, never on message text.
- **Tier 1 has teeth** — `tests/test_api_contract.py` pins the code registry
  and fails if a code disappears or a title drifts, verified by negative
  control. Retired rules keep their entry so historical locks and dossiers
  citing them stay readable.
- **`uel/api.py`: the envelope and the 1-vs-3 exit split.** "The model was
  rejected" and "the tool could not run" are opposite instructions; a caller
  that conflates them either thrashes on a healthy model or ignores a real
  rejection. `guard()` catches unexpected exceptions on purpose — an unhandled
  traceback exits 1 through a shell, which would let a kernel defect
  masquerade as an engineering verdict. Mints UEL0004.

### The generated adapter layer

- **`uel harness install --target claude-code|agents-md`** (ADR-0010): the seam
  where a harness-agnostic kernel meets a specific harness's reflexes.
  `claude-code` emits a PostToolUse compile gate (`uel check --json` on every
  edit to a `.uel` source or manifest, structured diagnostics back on exit 2 —
  the merge gate as a keystroke gate), a SessionStart work brief, merged hook
  wiring in `.claude/settings.json`, and the packaged skill via the existing
  `uel skill install` machinery. `agents-md` emits a vendor-neutral `AGENTS.md`.
  `uel harness check` is the drift gate; `uel harness show` prints without
  writing.
- **Generation, not authorship** — enforced, not asserted. Every token an
  adapter says about UEL is substituted from a live kernel table (the argparse
  tree via the new `cli.build_parser()`, `diagnostics.CODES` grouped into
  labelled bands, `expr.FUNCTIONS`/`CONSTS`, `units.UNITS`, `graph._KIND_MAP`,
  `project.MANIFEST`/`LOCK`/`SOURCE_SUFFIX`, the packaged `SKILL.md`, and
  `agentdoc.briefing()` quoted verbatim). Tests fail if any template contains a
  literal subcommand name, diagnostic-code band, or project filename — typing
  `uel check` into a template is a CI failure.
- **Adapters are directories of data** — `uel/adapters/<target>/adapter.json`
  plus templates, no per-target Python, budgeted and tested under 200 lines
  each (claude-code 193, agents-md 70). Adding a harness adds a directory;
  removing one is `rm -r`.
- **Merge, never clobber** — foreign hooks, matcher groups, permissions and env
  in an existing `settings.json` all survive; re-installing is a byte-level
  no-op; unparseable JSON is left untouched and reported; edited artifacts are
  kept unless `--force`.
- **Drift is a test failure** — this repository installs its own adapter and
  `tests/test_harness.py` fails if the installed copy differs from what the
  generator emits, extending the v0.5 skill-drift test to the whole harness.
  That is what makes an adapter safe to regenerate and cheap to throw away.
- **Graceful degradation** — the brief carries a ladder (`stale --rank`, then
  `agenda`, then plain `stale`) and the emitted hook probes each rung at
  *runtime* against the kernel actually installed, so an adapter works on
  either side of concurrent kernel work; the floor rung is asserted against the
  live CLI table. `doctor` is probed and surfaced only when present.
- Emitted hooks are stdlib-only, detect how to invoke the tool (entry point,
  else `python3 -m uel` with the repo on `PYTHONPATH` for an uninstalled
  checkout), and are silent no-ops when no kernel answers. 100 unit tests.
- No new diagnostic codes: the UEL11xx band is reserved and deliberately
  unused (ADR-0010) — adapter installation is not graph checking.

### The economics scheduler

Executes gap-analysis §2 moves 2 and 3 (ADR-0011). The substrate scheduled
cores; nothing scheduled the two resources that actually bound the loop —
agent attention and oracle contact. Advice, not authority: the checker still
gates and `uel build` still walks in dependency order.

- **`uel stale --rank`** — the stale frontier in value order, scored by nine
  normalized signals joined from data the kernel already computes: broken runs
  and failed `verify` contracts, target verdicts (violated / band-across-the-
  line / pending), budget erosion, envelope-fence pressure, requirement trace,
  blast radius, uncovered model hazards, stub maturity, evidence age. Every
  row ships its terms — `value × weight = contribution`, summing exactly to
  the score — because a rank with no visible arithmetic is an oracle. Ties
  break toward topological order; `frontier` marks what is buildable now;
  `--all` includes fresh nodes carrying obligations a rebuild cannot fix.
- **`uel query info-value [quantity]`** — which single test to run next:
  `tightening × (1 + Σ consumer weight) × (1 + margin pressure)`. Consumers
  are weighted by their *own* attention score, not counted, so tightening a
  band that feeds a violated target outranks tightening one that feeds three
  nodes nobody is waiting on. Unvalued budget leaves are candidates even
  though they declare no band — they are the holes that make a rollup
  indeterminate. `--sensitivity` scales tightening by measured elasticities
  (v0.6 perturbation machinery; costs core runs, hence opt-in).
- **Normalized terms** — every signal is [0, 1], so a weight means the same
  thing in a 7-node slice and a 50-node chain. Evidence age is measured inside
  the lock, never against wall-clock: a ranking that changes because a day
  passed is not reproducible.
- New diagnostics UEL0901–0903 (dead stale work, no declared ignorance,
  measurement decides a verdict), raised by the economics queries only —
  the merge gate does not carry opinions about what is worth doing.
- New conformance kind `economics/` (5 cases pinning rank order, term values,
  frontier flags, the cone-vs-fence tradeoff from both sides, the
  consumer-weight upgrade in isolation, and the indeterminate-budget rule);
  34 new unit tests. Gates: 106 tests, 72 cases, three examples green.
- No version bump and no relock: `uel.__version__` feeds `tool_pins()` and so
  every recipe hash. This change adds two read-only queries and touches no
  locked semantics, so the bump and relock belong to whoever cuts the release.

### `uel doctor` — audit the model, and say where belief is load-bearing

Ports the v0.1.3 audit onto v0.6, where there are contract verdicts, target
verdicts, hazard dispositions and transparent expr cores to grade.

- **The trust ledger** — what fraction of a model is verified by construction,
  verified by contract, or trusted on the author's word. On `apache-one` that
  reads 0%/0%/100%, with every uncertainty hand-asserted: the single most
  useful sentence anyone has written about that model.
- **Asserted-vs-propagated uncertainty** (UEL1050–1052) — flags outputs whose
  band is authorial assertion rather than computed propagation, including a
  hard band derived from an input the graph says is still `± cal`.
- **Self-authenticating** — every finding cites the hash it came from, so the
  report can be checked rather than believed. Never files anything: reporting
  upstream is an explicit decision, not a side effect of an audit.
- 21 diagnostics UEL1000–1080; `--strict` exits nonzero for use as a gate.
- Root cause of the v0.1.3 red gate, fixed rather than reproduced: its tests
  read gitignored build artifacts that existed only on the author's machine.
  A commit about detecting drift shipped a suite that had drifted from its own
  repository.

## v0.6.0 — the recursive-detail harness (2026-08-05)

The devil is in the details at every layer, so the harness now asks about
them mechanically: the solver answers the question you asked; the checker
asks the ones you didn't.

- **Registered models carry hazard lists** (ADR-0009) — a new `model` library
  kind: `model beam.euler_bernoulli { hazard lateral_torsional_buckling
  "Mcr falls with the cube of flange thickness…" }`. A hazard is a failure
  mode the model is structurally blind to. Using a registered model obliges
  the project per hazard: some analysis `covers` it, or the using framing
  `waive`s it `because "reason"` (the reason is grammatically required —
  a waiver without a reason is denial) — else UEL0510, carrying the
  registry's why-text. `uel/stdlib/models.uel` ships eighteen registrations
  across structures, aero, thermal, RF, power, controls, and tracking; the
  hazard names join the claim taxonomy. Status carries the coverage ledger.
- **Applied, not just shipped**: the check surfaced 34 unanswered questions
  across the three examples. Answers: one new analysis the checker forced
  into existence (the ground station's `VortexShedding` — Strouhal vs first
  mode, separation ≈ 31, computed with a target) plus 25 waivers that are
  real engineering arguments (the apache-one spar waives lateral-torsional
  buckling because a closed circular tube has no weak axis; the UPS waives
  Peukert at C/8; the drag models waive the regime shift because the
  subcritical Cd bounds the load). Zero boilerplate waivers.
- **Sensitivity as a query** — `uel query sensitivity <node>`: every input
  perturbed +5 % in SI through the probe machinery, elasticity matrix
  e = %Δout/%Δin per output, superlinear inputs flagged ▲ (WindLoads:
  wind_op e = +2.05 ▲, the V² law visible in one command), dead inputs
  flagged · (insensitive or not actually wired in — both worth knowing).
- **Convergence contracts** — `verify converged residual <= 1e-6`: python
  cores' `convergence` metrics now persist into the lock (`run.convergence`)
  and the contract binds them right after the run. Metric missing → failed
  run ("silence is not convergence"); over threshold → UEL0808. Closed-form
  cores cannot declare it (there is no iteration to converge) — and since
  every shipped example core is closed-form, the live demonstration is a
  genuinely iterating Newton solver in the test suite, graded both passing
  and failing (the ADR-0008 load-bearing-or-dead rule, applied again).
- Schema 0.3 (node kind `model`, framing `covers`/`waives`, verify kind
  `converged` — all omit-empty). Full relock under 0.6.0: every previously
  locked value reproduced identically across all three examples; the only
  content change is the new VortexShedding node. 72 unit tests, 67
  conformance cases.

## v0.5.0 — agents as first-class citizens (2026-08-05)

Two arrival paths, both native now. An agent that fetches the tool gets a
tool that briefs it; an agent that lands in a repo cold finds the map at the
door. One source of truth for both: the package itself.

- **`uel agent`** — the tool describes itself to the model using it: the
  loop, a six-line syntax card, the hard rules (each one a real debugging
  session from the builds), and — generated from the LIVE kernel tables so
  they cannot drift — the expression functions and constants, the level
  units, the diagnostic-code families, and the CLI surface.
- **`uel skill`** — the operating skill (`uel/skill/SKILL.md`, shipped as
  package data) distills three projects of scar tissue: the check→fix→
  build→judge loop, the gotchas, verification-contract practice, the
  zero-trust review order, the multi-agent contract-and-stubs pattern, and
  a Never list. `uel skill install <dir>` drops it into a project's
  `.claude/skills/uel-engineer/`; `uel skill show` prints it for any other
  harness. This repository installs its own copy, and a test fails CI if
  the installed copy drifts from the packaged one.
- **`uel init <dir>`** — a green-by-construction scaffold: requirement →
  ledgered stub → expr analysis with a computed acceptance target, plus
  AGENTS.md and the skill, checking and building clean on first contact.
- **Stub nominals carry declared bands** — `core stub { eta = 0.8 ± 5 % }`
  (abs/rel/cal), round-tripped canonically, type-checked against the
  nominal's unit, and widened into downstream worst-case enclosures. Found
  because the scaffold's own example needed it: the v0.2 stub grammar had
  lost what the v0.1 python stubs always had.
- Root `AGENTS.md` (+ `CLAUDE.md` pointer) for repo-resident agents;
  `pyproject.toml` version is now read from `uel.__version__` (it had
  silently pinned 0.1.0); skill ships in package data.

## v0.4.0 — the quality pass (2026-08-05)

Same functionality, fewer lines, graded by the same suite before and after:
54 unit tests, 63 conformance cases, all three examples check/format clean,
and — the strictest referee — every committed lock reported **all-fresh**
against the refactored kernel before the version bump (byte-identical
canonical encodings and hashes), then re-locked to bit-identical values after.

- `uel/graph.py`: serialization is now spec-driven — each class declares
  SPEC rows consumed by one generic emitter/reader pair; cross-field checks
  live in small `_post` hooks. Emission semantics unchanged to the byte.
- One `span_of` in `diagnostics` (was six per-module copies); the small
  modules (canon, lockfile, dfm, staleness, hashing, checker, diagnostics)
  rewritten to their essentials with docstrings tightened to the
  load-bearing sentences.
- Vertical density: single blank lines, 281 single-statement guards folded,
  three-line banners collapsed. 9,698 → 8,567 kernel lines (−11.7%) with
  diagnostics prose — the product surface agents iterate against —
  deliberately untouched. A line-join sweep at 100 columns found only 2
  candidates: the code was already written at width.
- Where the remaining mass lives, on the record: ~1/3 subsystem logic that
  is simply distinct (parser, resolver, three core engines, five
  projections), ~1/4 diagnostic messages/reasons/fixes (cutting these
  breaks the fix-loop), and data tables (units vocabulary, code registry).
  Halving again means deleting features or the prose that makes errors
  actionable — declined, and this entry is the receipt.

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
