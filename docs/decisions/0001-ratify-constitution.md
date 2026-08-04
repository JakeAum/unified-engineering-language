# ADR-0001 — Ratify the constitution

*Status: accepted · Stage 0 · 2026-08-04*

Decision nodes in this log deliberately follow the epistemic structure of spec §3.1
(intent, framing, knowns, derivation, judgment). The org runs on the language's own
primitives from day zero (program §3.3, §9.1).

## Intent

Establish the change-controlled documents under which all subsequent work is graded
(program §3.1: "the constitution").

## Framing

The program plan requires a constitution loaded by every context at boot, consisting of
`spec.md` (what UEL is) and `program.md` (how it gets built). Ratification is a Stage 0
act of the orchestrator context (program §9, Stage 0).

## Knowns

- `docs/spec.md` — UEL language design document, Draft 0.1 (August 2026).
- `docs/program.md` — UEL program plan, Draft 0.1.
- `LICENSE` — MIT, maintainer-of-record JAM (pre-settled by the principal in the
  repository seed; a §2.3 one-time formality already exercised).

## Derivation

Copied verbatim into `docs/`. Content-addressed by Git from this commit forward.
§1 of each document and program §2.3 change only by principal amendment (program §10);
everything else is amendable through this decision log, subject to the merge gate.

## Judgment

Ratified. The repository seed (`LICENSE`, `README.md`) shows the principal has already
exercised the bootstrap formalities; no further human authority is required to begin
Stage 0. Residual doubt: none material.
