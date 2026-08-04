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
| Checks | `uel/conservation.py` | Port/domain compatibility, static junction balance, budget rollups. |
| Checks | `uel/envelopes.py` | Value-predicate containment; structural-claim entailment closure. |
| Identity | `uel/hashing.py` | Tolerance-quantized content hashes; Merkle recipe hashes. |
| Identity | `uel/staleness.py` | Lockfile diff → stale set with reasons. |
| Runtime | `uel/scheduler.py` | Topological walk of the stale set; executes cores via the JSON core protocol. |
| Loop | `uel/calibration.py` | Measurement write-back, envelope tightening, discrepancy events. |
| Surfaces | `uel/projections.py` | Compiled, hash-stamped projections: BOM, ICD, work instructions, status. |
| Surfaces | `uel/diagnostics.py` | Structured diagnostics (JSON + human render). Error-code registry. |
| Surfaces | `uel/cli.py` | `uel check / build / fmt / stale / hash / graph / project / calibrate / query`. |

## Grading artifacts

- `conformance/` — the suite every change is graded against. Authored spec-first
  (from `docs/spec.md` section text), independent of implementation internals.
- `tests/` — implementation unit tests (may know internals; conformance may not).
- `docs/decisions/` — the decision log. Settled decisions are amended, not re-litigated.

## Open problems (live status)

Tracked in `docs/spec.md` §10. R1 (envelope formalism) de-risk pair set lives at
`conformance/cases/derisk/`. R2 (leverage) instrumented in `examples/apache-one/`.
