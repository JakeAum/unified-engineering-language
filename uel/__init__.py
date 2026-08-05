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
"""

__version__ = "0.5.0"

# The edition this kernel implements. Editions are the unit of breaking change
# (spec/program §7.3); the schema is frozen per edition.
EDITION = "2026"
SCHEMA_VERSION = "0.2"
