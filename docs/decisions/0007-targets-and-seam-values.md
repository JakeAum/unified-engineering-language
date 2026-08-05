# ADR-0007 — Targets and seam values: acceptance is computed, not narrated

*Status: accepted · v0.2 · 2026-08-05 · extends spec §2.5 (envelopes) and §3.2 (outputs)*

## Intent

Two v0.1 retrospective findings, one root cause:

1. Whether a design *meets its requirement* lived in judgment prose and test
   JSON files — the language had no way to say "this output exists to satisfy
   that bound".
2. Envelope fences at analysis-to-analysis seams compared **name-matched
   variables in framings**, not the values actually flowing; the ground-station
   reviewer's seam-direction catch was a symptom of that gap.

## Decision

- **Output targets.** An output may declare its acceptance bound, by literal
  or by reference:

      outputs { margin_db : dB ± target >= req.LNK-002.min_margin_db }

  After every build the locked value is re-verdicted: a violated target is a
  compile-visible **error** (UEL0804) that reds the merge gate; a met-on-the-
  nominal target whose ± band crosses the line is a **warning** — the
  "passing on the nominal" situation handed to the reviewer explicitly; an
  unbuilt target is announced pending (UEL0805). The status projection carries
  the target ledger.
- **Seam values.** A fence on a known that references an upstream output is
  checked twice: statically, fence type vs output type (UEL0505 — a `dB`
  fence cannot guard a `dBW` value); and against the lock, fence vs the
  **value actually flowing** with its band (UEL0806), with the producer named
  in the diagnostic.
- **Runtime gating.** Lock-derived verdicts (UEL0804/0806) red-gate merges
  but do **not** gate the scheduler — only a rebuild can refresh the values
  they judge, so `uel build` runs and then re-verdicts against the new lock.
- **Instance designators.** `contains X x N` mints addressable slots
  (`X#1…#N`) surfaced in the BOM and `uel query instances`; per-serial
  as-built overlays target those designators. Identity for instances is an
  addressing scheme in v0.2, not per-instance graph state — that remains a
  v0.3 question.

## Consequences

- The ground-station margin requirement is now a declared target; on the
  1/10-cost excursion the checker says the quiet part on every run — the
  worst-case band crosses the 3 dB floor — as a standing warning that TRADE.md
  previously carried as prose.
- The v0.1 "min_margin_db" known that existed only so a Python core could
  print "meets" is gone; the bound is language, not core input.
- A producer whose value drifts outside a consumer's fence is caught at check
  time with both sites cited, whether or not any variable names match.

## Revisit

If targets need two-sided bands or statistical acceptance (Pk > 0.99), extend
the target grammar — do not fall back to prose.
