# UEL semantic schema — edition 2026, schema 0.2

*Phase 1 artifact (program §4). This schema is defined before concrete syntax and is
frozen for the edition: the surface language (Phase 2) parses **to** it, hashing
(Phase 3) hashes **over** it, and the conformance suite grades round-trip stability
**of** it. Changes after freeze are edition-level events (spec/program §7.3).*

Reference implementation: `uel/graph.py` (model), `uel/canon.py` (encoding).
Conformance: `conformance/cases/schema/`.

## 1. Canonical form

A graph document is a JSON object encoded canonically:

- UTF-8; keys sorted; separators `","`/`":"`; floats in shortest-round-trip repr;
  NaN/±Inf rejected.
- **Omit-empty:** `null`, `""`, `{}`, `[]`, and single-value enums at their default
  are omitted. Absent and default are the same statement.
- Lists with no inherent order are stored sorted (`contains` by ref, `connections` by
  (from, to), claim `entails`/`excludes` lexically). Maps are used wherever keys are
  natural (ports, quantities, budgets, outputs, predicates), so ordering questions
  do not arise.

Round-trip invariant (conformance-graded): `decode → encode` is a fixpoint after one
normalization pass, and `encode(decode(x))` is byte-identical for already-canonical `x`.

## 2. Document

```json
{
  "uel_schema": "0.2",
  "edition": "2026",
  "nodes": { "<qualified-name>": { "kind": "...", ... } },
  "connections": [ { "from": "comp.port", "to": "comp.port" } ]
}
```

**Naming.** Requirements live under `req.`; library nodes under `lib.<library>.`
(e.g. `lib.domains.electrical`, `lib.claims.rigid`, `lib.materials.AL7075_T6`,
`lib.process.cnc_3axis`); project components and analyses are top-level. Members are
addressed by dotted path: `spar_v7.section_Ixx` (quantity), `battery.main_out`
(port), `SparDynamic.outputs.first_bending_mode` (analysis output; the `outputs.`
segment is required to address outputs).

## 3. Quantity — the universal scalar

`(value or interval, unit, uncertainty, provenance, confidence)` — spec §2.4.

```json
{ "value": 240.0,          // or [lo, hi] interval; absent = declared-but-TBD
  "unit": "g",             // surface unit expression; absent = dimensionless
  "unc": { "kind": "abs", "value": 10.0 },   // abs | rel (fraction) | cal (pending)
  "prov": { "kind": "measured", "site": "model/spar.uel:12",
            "detail": "test W12 run 3", "ts": "2026-08-01T00:00:00Z" },
  "conf": 0.95 }
```

`prov.kind` ∈ declared | measured | vendor | derived | estimate.

## 4. Node kinds

Kernel kinds: `component`, `analysis`, `requirement`, plus `connections`.
Library kinds (representable by the kernel, shipped as libraries): `domain`,
`claim`, `material`, `process`.

### component
`level` (functional | behavioral | physical), `ports{}`, `quantities{}`,
`budgets{}` (`op` ≤/≥, `limit`, `at_qty`), `envelope`, `contains[]` ({ref, count}),
and the binding fields on physical components: `realizes` (refinement edge to the
functional identity), `process` (activates a DFM ruleset), `material`, `geometry`
(ref to the geometry analysis producing this shape), `datasheet` ({source, sha256}).

### port (owned by component)
`domain` (e.g. `electrical`, `mechanical.translation`), `dir` (in | out | inout,
w.r.t. the owner), `attrs{}` (quantities; checked against the domain's effort/flow
dimensions), `protocol` (data ports).

### envelope (spec §2.5)
```json
{ "predicates": { "load": {"lo": 0.0, "hi": 18.0, "unit": "kN"} },
  "claims":   { "rigid_root": "root fitting stiffness >> spar; see AN-009" },
  "requires": { "elastic_modes": "flutter needs the first bending mode" } }
```
`predicates` are the SMT-decidable layer (boxes in v0.1; one-sided bounds allowed).
`claims` are structural claims **made**; `requires` are structural claims **needed
of upstream**. Compatibility is judged against the claim taxonomy's entailment
closure (Phase 4).

### analysis (spec §3)
`akind` (analysis | geometry), `intent` ({ref, text}), `framing` ({model, envelope}),
`knowns{}` (local name → graph ref; **references, never copies**), `params{}`
(literal quantities local to this node), `core` ({lang, path, text}), `outputs{}`
({unit, unc, artifact, target}), `judgment` ({status, text, doubts}).
Geometry nodes are ordinary shell-and-core analyses whose cores must also return
topological assertions (spec §6.2); the scheduler enforces this at run time.

v0.2 (ADR-0005/0007): `core.lang` ∈ python | expr | stub. For expr/stub cores
`core.text` holds the canonical formatted body — it IS the content that hashes;
`core.path` is empty. `outputs.<name>.target` = `{"op": ">="|"<=",` then exactly
one of `"ref": "<value reference>"` or `"value": {<quantity>}}` — the acceptance
bound this output is re-verdicted against on every build.

### requirement
`text`, `quantities{}`.

### domain (library)
`dclass` (power | material | data), `effort` {name, unit}, `flow` {name, unit}.
For power domains, effort × flow must be power — the units checker verifies this
when the library loads.

### claim (library)
`entails[]`, `excludes[]` — the hand-authored entailment web for structural claims.

### material (library)
`quantities{}` (density, E, yield_strength, …).

### process (library)
`rules{}`: each rule is `{feature, op, limit?, message}` with op ∈ ≥ | ≤ | forbid |
require, checked against feature quantities declared by geometry outputs.

## 5. Identity vs. record fields

Every field is classified (markers in `uel/graph.py`):

- **identity** — semantic content. Participates in node/recipe hashes.
- **record** — authorship and narrative metadata: `src` sites, `doc`, provenance
  `site`/`detail`/`ts`, `conf`, judgment prose, intent `text`.
  Editing a record field NEVER invalidates downstream work. Moving a declaration to
  a different line is a record change. Writing judgment is a record change.

## 6. Hashing rules (declared here, implemented in Phase 3)

- `node_hash` = SHA-256 over the canonical encoding of the node's identity fields,
  with every quantity **quantized to its declared tolerance** (project
  `[tolerances]`; spec §4.3 draft rule) before encoding.
- `recipe_hash(analysis)` = SHA-256 over: identity fields ∪ resolved values of all
  `knowns` (quantized) ∪ content hashes of core files ∪ pinned tool versions.
  Early cutoff is by construction: if an upstream re-run reproduces equal-within-
  tolerance outputs, downstream recipe hashes do not move.
- Core file **content** is identity; its path is not. CAD kernel / tool versions are
  identity (spec §6.2). For expr/stub cores the canonical body text is the content.
- Quantized identity records the quantity **type**, not the surface unit: the
  dimension vector, prefixed with a `"dB"` marker for level quantities (ADR-0006) —
  `850 mm` == `0.85 m`, `52 dBm` == `22 dBW`. Level types may declare their own
  tolerance grids (`"0.001 dB"`), applied on the dB scale.
