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
| Loop | `uel/calibration.py` | Measurement write-back (overlays, per-serial as-built), tightening, discrepancy events; candidate entailment rules from output discrepancies (ADR-0005). |
| Loop | `uel/attention.py` | The economics scheduler (ADR-0005): stale-set attention ranking, information value of candidate measurements, the agenda. Advice, not authority — the checker still gates. |
| Surfaces | `uel/projections.py` | Compiled, hash-stamped projections: BOM, ICD, work instructions, status. Sealed on write with a body digest, so hand-edits are provable (ADR-0007). |
| Surfaces | `uel/diagnostics.py` | Structured diagnostics (JSON + human render). Error-code registry. |
| Surfaces | `uel/cli.py` | `uel init / check / build / fmt / stale [--rank] / hash / graph / project / calibrate / query / agenda / doctor`. |
| Health | `uel/doctor.py` | The checkup: doctored-vs-stale reports, lock integrity, seeded staleness honesty, formatter/round-trip/diagnostic-quality self-audit. Kernel-class findings become a redacted upstream issue (ADR-0007). |
| Adoption | `uel/scaffold.py`, `uel/templates/` | `uel init`: the starter project plus the agent harness (boot context, loop skill, compile-on-edit and agenda-on-wake hooks, CI gate, loop protocol). Merges, never clobbers; no-ops without the kernel (ADR-0006). |

## Grading artifacts

- `conformance/` — the suite every change is graded against. Authored spec-first
  (from `docs/spec.md` section text), independent of implementation internals.
- `tests/` — implementation unit tests (may know internals; conformance may not).
- `docs/decisions/` — the decision log. Settled decisions are amended, not re-litigated.

## Open problems (live status)

Tracked in `docs/spec.md` §10. R1 (envelope formalism): **discharged 11/11**
(ADR-0003, `conformance/cases/derisk/`). R2 (leverage): substrate-mechanical
numbers recorded in `docs/boot/leverage-v0.1.md`; org-level claim open until the
user org flies — the standing loop (`docs/org/user-org-loop.md`) exists to
discharge it. R4 (gate gamed): round 1 findings fixed and pinned (ADR-0004).
R5 (hash semantics): tolerance grids + pinned seeds shipped; sensitivity-aware
staleness is v0.2. Strategy: `gap-analysis-v0.1.md` (this directory) names six
gaps and five moves; moves 2/3/5 (attention ranking, info-value, empirical
entailment growth) shipped as ADR-0005; move 1 (the continuous loop) is stood
up per the org runbook; move 4 (governance-by-recorded-argument) is triggered
by the next genuine merge conflict (program §8 R7). Deliberately not built in
v0.1 (spec §11 puts them in v0.2/0.3): LSP, FMU transport, surrogates, remote
execution, SysML bridges, distributor refresh, sensitivity staleness.
