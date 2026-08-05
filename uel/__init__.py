"""UEL — Unified Engineering Language. Reference implementation (v0.1 kernel proof).

The kernel admits exactly four kinds of thing: components, ports, quantities, and
claims (analyses). Everything else is library. See docs/spec.md.
"""

__version__ = "0.1.2"

# The edition this kernel implements. Editions are the unit of breaking change
# (spec/program §7.3); the schema is frozen per edition.
EDITION = "2026"
SCHEMA_VERSION = "0.1"
