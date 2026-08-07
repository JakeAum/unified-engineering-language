"""UEL — Unified Engineering Language. Reference implementation (v0.2).

The kernel admits exactly four kinds of thing: components, ports, quantities, and
claims (analyses). Everything else is library. See docs/spec.md.

v0.2: level quantities as types (ADR-0006), expression cores (ADR-0005),
targets and seam values (ADR-0007). v0.3: verification contracts, declared
wrappers, the `uel pack` review dossier (ADR-0008). v0.4: the quality pass —
same functionality, spec-driven serialization, denser style, suite-graded.
v0.5: the agent-native surface — `uel agent` (self-briefing from live tables),
`uel init` (green-by-construction scaffold), `uel skill` (the packaged
operating skill), stub nominals with declared bands.
v0.6: the recursive-detail harness — registered models carry hazard lists
(cover or waive each, UEL0510), `uel query sensitivity` (elasticities by
perturbation), convergence contracts (`verify converged`) on python cores.
Then the generated adapter layer (ADR-0010): `uel harness install` emits an
agentic harness's hooks and boot context from live kernel tables — substance
portable, reflexes local, and a drift test so adapters stay disposable.
"""

__version__ = "0.6.0"

# The edition this kernel implements. Editions are the unit of breaking change
# (spec/program §7.3); the schema is frozen per edition.
EDITION = "2026"
SCHEMA_VERSION = "0.3"
