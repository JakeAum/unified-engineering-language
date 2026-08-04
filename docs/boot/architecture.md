# Boot library — architecture map

*Owned by the Historian role (program §3.2). Load this before touching the kernel.
Kept deliberately short; prune as aggressively as you grow it.*

## What exists (updated per phase)

| Layer | Module | Responsibility |
|---|---|---|
| Schema | `uel/graph.py` | The semantic graph: the kernel's four kinds (component, port, quantity, claim/analysis) plus library kinds (domain, claim taxonomy, material, process). Canonical JSON round-trip. |
| Schema | `uel/canon.py` | Canonical serialization: one byte-stable JSON encoding used by round-trip and hashing. |
| Syntax | `uel/source.py`, `uel/lexer.py`, `uel/parser.py` | Plain-text surface → AST. Hand-written recursive descent. |
| Syntax | `uel/formatter.py` | The one zero-config formatter (idempotent, AST-preserving). |
| Semantics | `uel/units.py` | Dimensions as a free-abelian-group checker; unit table; affine temperature. |
| Semantics | `uel/resolver.py` | Names → graph; builds `GraphDoc` from ASTs + libraries. |
| Checks | `uel/conservation.py` | Port/domain compatibility, net effort/flow checks, energy balance, budget rollups. |
| Checks | `uel/envelopes.py` | Value-predicate containment; structural-claim entailment closure; binding covers. |
| Checks | `uel/dfm.py` | Process rulesets vs lock-recorded geometry feature claims. |
| Checks | `uel/checker.py` | The compile-time pipeline orchestrator (gates the scheduler). |
| Identity | `uel/hashing.py` | Tolerance-quantized, SI-normalized content hashes; recipe hashes with per-part breakdowns. |
| Identity | `uel/lockfile.py` | uel.lock: recorded recipes, outputs, features, assertions, run provenance. |
| Identity | `uel/staleness.py` | Lock diff → fresh/stale/missing with named reasons; topological order. |
| Runtime | `uel/scheduler.py` | Topological walk of the stale set; executes cores via the JSON core protocol; early cutoff. |
| Loop | `uel/calibration.py` | Measurement write-back (overlays, per-serial as-built), tightening, discrepancy events. |
| Surfaces | `uel/projections.py` | Compiled, hash-stamped projections: BOM, ICD, work instructions, status. |
| Surfaces | `uel/diagnostics.py` | Structured diagnostics (JSON + human render). Error-code registry. |
| Surfaces | `uel/cli.py` | `uel check / build / fmt / stale / hash / graph / project / calibrate / query`. |

## Grading artifacts

- `conformance/` — the suite every change is graded against. Authored spec-first
  (from `docs/spec.md` section text), independent of implementation internals.
- `tests/` — implementation unit tests (may know internals; conformance may not).
- `docs/decisions/` — the decision log. Settled decisions are amended, not re-litigated.

## Open problems (live status)

Tracked in `docs/spec.md` §10. R1 (envelope formalism): **discharged 11/11**
(ADR-0003, `conformance/cases/derisk/`). R2 (leverage): substrate-mechanical
numbers recorded in `docs/boot/leverage-v0.1.md`; org-level claim open until the
user org flies. R4 (gate gamed): round 1 findings fixed and pinned (ADR-0004).
R5 (hash semantics): tolerance grids + pinned seeds shipped; sensitivity-aware
staleness is v0.2. Deliberately not built in v0.1 (spec §11 puts them in
v0.2/0.3): LSP, FMU transport, surrogates, remote execution, SysML bridges,
distributor refresh, sensitivity staleness.
