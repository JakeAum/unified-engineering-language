"""UEL — Unified Engineering Language. Reference implementation (v0.2).

The kernel admits exactly four kinds of thing: components, ports, quantities, and
claims (analyses). Everything else is library. See docs/spec.md.

v0.2 ("the compiler sees inside the physics"): level quantities as types
(ADR-0006), expression cores with dimensional inference and interval
uncertainty (ADR-0005), output targets and seam-value checks (ADR-0007).
"""

__version__ = "0.2.0"

# The edition this kernel implements. Editions are the unit of breaking change
# (spec/program §7.3); the schema is frozen per edition.
EDITION = "2026"
SCHEMA_VERSION = "0.2"
