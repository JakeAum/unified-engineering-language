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
| Semantics | `uel/units.py` | Dimensions as a free-abelian-group checker; unit table; affine temperature; level (dB-family) units with reference-carrying types (v0.2, ADR-0006). |
| Semantics | `uel/resolver.py` | Names → graph; builds `GraphDoc` from ASTs + libraries; target resolution; expr-core type inference pass. |
| Semantics | `uel/expr.py` | The declarative expression layer (v0.2, ADR-0005): AST, canonical printing, dimensional/level inference, interval evaluation. |
| Checks | `uel/conservation.py` | Port/domain compatibility, net effort/flow checks, energy balance, budget rollups. |
| Checks | `uel/envelopes.py` | Value-predicate containment; structural-claim entailment closure; binding covers; seam values vs locked flow (v0.2). |
| Checks | `uel/contracts.py` | Output targets re-verdicted against the lock; verify-against cross-checks; stub maturity ledger (ADR-0007/0008). |
| Checks | `uel/dfm.py` | Process rulesets vs lock-recorded geometry feature claims. |
| Checks | `uel/checker.py` | The compile-time pipeline orchestrator (gates the scheduler). |
| Identity | `uel/hashing.py` | Tolerance-quantized, SI-normalized content hashes; recipe hashes with per-part breakdowns. |
| Identity | `uel/lockfile.py` | uel.lock: recorded recipes, outputs, features, assertions, run provenance. |
| Identity | `uel/staleness.py` | Lock diff → fresh/stale/missing with named reasons; topological order. |
| Runtime | `uel/scheduler.py` | Topological walk of the stale set; Python cores via the JSON core protocol, expr/stub cores kernel-evaluated; early cutoff; monotone/case verification probes (ADR-0008). |
| Loop | `uel/calibration.py` | Measurement write-back (overlays, per-serial as-built), tightening, discrepancy events. |
| Surfaces | `uel/projections.py` | Compiled, hash-stamped projections: BOM, ICD, work instructions, status, and the `uel pack` review dossier (ADR-0008). |
| Surfaces | `uel/diagnostics.py` | Structured diagnostics (JSON + human render). Error-code registry. |
| Surfaces | `uel/cli.py` | `uel check / build / fmt / stale / hash / graph / project / pack / calibrate / query` (provenance + instances + sensitivity) / agent / init / skill / harness. `build_parser()` is the live CLI table the agent-facing surfaces generate from. |
| Surfaces | `uel/agentdoc.py` | `uel agent` (self-briefing from live tables), `uel skill`, `uel init`. |
| Surfaces | `uel/harness.py` + `uel/adapters/` | `uel harness install` — the generated adapter layer (ADR-0010). The only module that knows an agent harness exists; each adapter is a directory of data, under 200 lines, drift-gated by CI. |

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
staleness still open.

v0.2 (ADR-0005/0006/0007) closed the retrospective's top findings: the
expression layer (`uel/expr.py`), level quantities (`uel/units.py`),
targets/seams (`uel/contracts.py`, `uel/envelopes.py`). v0.3 (ADR-0008)
operationalized zero-trust review: verification contracts (against/monotone/
case), declared tool pins + interface manifests, the `uel pack` dossier, and
the trust ledger. v0.5 made the tool agent-native (`uel agent`, the packaged
skill, `uel init`); v0.6 (ADR-0009) added the recursive-detail harness:
the physics-model hazard registry (`uel/stdlib/models.uel`, UEL0510
cover/waive obligations), the sensitivity query, and convergence contracts
(`verify converged`). ADR-0010 added the generated adapter layer
(`uel harness install`): the exoskeleton's seam onto whatever agentic harness
is calling it, generated from live kernel tables and drift-gated so the
adapters stay disposable. Still deliberately unbuilt: LSP, FMU import (the
manifest pattern exists; the shell generator waits for a real FMU), remote
execution, SysML bridges, distributor refresh, sensitivity-aware staleness,
expression conditionals/interp tables, per-instance graph state (hazard
coverage is therefore project-granular, not per-subject), statistical
uncertainty.
