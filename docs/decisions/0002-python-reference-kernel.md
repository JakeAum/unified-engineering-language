# ADR-0002 — v0.1 kernel is a zero-dependency Python reference implementation

*Status: accepted · Stage 0 · 2026-08-04 · amends program §4 (amendable region, program §10)*

## Intent

Choose the implementation substrate for the v0.1 kernel proof (spec §11) such that the
whole v0.1 scope — parser → resolver → units → conservation → envelopes → hashing →
staleness → scheduler → calibration write-back — ships *complete and load-bearing*
behind the merge gate.

## Framing

- Model: engineering-economics trade, not language advocacy.
- Boundary: v0.1 only. The question "what should the production kernel be written in"
  is explicitly out of frame; it re-opens when the conformance suite freezes semantics.
- Assumptions:
  - `single_build_context` — because v0.1 is built by one orchestrator lineage
    (program §9, Stage 0–1), completeness risk dominates throughput risk.
  - `semantics_over_speed` — because nothing in v0.1's exit criteria is
    performance-bound (50-node staleness demo answers in milliseconds in any language).

## Knowns

- program §4 (draft): "Rust kernel; Python as the blessed core/SDK language."
- spec §1.4-1: "Load-bearing or dead ... anything merely descriptive will drift and must be cut."
- spec §5.1: analysis cores and geometry are Python-first regardless of kernel language.
- Environment: Python 3.11 present; Rust toolchain present; no third-party Python
  packages installed (no pytest, no z3).

## Derivation

Alternatives considered:

1. **Rust kernel now.** Faithful to program §4 draft text. Cost: the v0.1 surface is
   large (nine subsystems); a partial Rust kernel that reaches Phase 3 of 5 is
   *descriptive, not load-bearing* — the exact failure mode spec §1.4 kills. Also
   doubles the substrate (Rust kernel + Python cores) before any user exists.
2. **Python reference kernel now, Rust port when semantics freeze.** Ships the whole
   v0.1 loop; the conformance suite (built spec-first, separate lineage) becomes the
   fixed target that makes a later Rust port a mechanical, gradeable task instead of a
   re-design. Zero runtime dependencies (stdlib only) so the user org can run the
   checker anywhere Python exists.
3. **Hybrid (Rust parser, Python rest).** Worst of both: FFI seam tax paid before any
   performance need is demonstrated.

Chosen: **(2)**. The conformance suite is the real kernel; the Python implementation is
its first conforming instance.

## Judgment

Accepted. This is the program's own thesis applied to itself: calibrate against
observed constraints rather than speculate. Kill criterion for this decision: if
compile-time checking of a real user-org graph exceeds interactive latency
(seconds, spec §4.4) and profiling shows the substrate rather than the algorithm,
the Rust port stops being deferred. Residual doubt: none blocking; revisit is cheap
because the conformance suite pins semantics.
