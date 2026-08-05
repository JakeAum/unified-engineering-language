---
name: uel-engineer
description: >
  Author, verify, and review engineering designs in UEL (Unified Engineering
  Language) — a content-addressed, typed graph of engineering claims where the
  compiler checks units, envelopes, budgets, and formulas, and every number has
  a provenance chain. Use when a repository contains uel.toml or .uel files,
  when asked to design or analyze hardware with auditable physics, or when
  reviewing another agent's engineering analysis.
---

# UEL engineer

You are working in a language built FOR agents. Trust the compiler more than
your memory: it checks dimensions inside formulas, fences at every seam,
budgets, acceptance targets, and verification contracts — and its diagnostics
carry machine-applicable fixes. When `uel check` disagrees with you, it is
almost always right; three projects were built this way and the checker caught
its own authors repeatedly.

## Orientation (any repo, 60 seconds)

```sh
uel agent                    # the tool describes itself: syntax, functions, codes
uel check <dir>              # does the graph compile? what is stale?
uel project status <dir>     # requirements -> analyses -> verdicts + trust ledger
uel pack <AnalysisName> <dir>  # one node's full epistemic chain, context-sized
uel query provenance <ref> <dir>  # where did this number come from?
```

No repo yet? `uel init <dir>` scaffolds a green-by-construction project.

## The loop (always the same)

1. Edit `.uel` sources (never `uel.lock`, never files under `out/`).
2. `uel check` — read EVERY diagnostic. Each has a stable code, a `reason`
   (why the rule exists), and often a `fix:` you can apply verbatim.
3. `uel build` — runs exactly the stale cone, re-verdicts targets, seams, and
   verification contracts against the new lock. Early cutoff means a
   sub-tolerance change re-runs nothing: that is correct, not a bug.
4. Record judgment: `judgment accepted "<what the numbers say>" doubts
   "<what would change your mind>"`. Doubts are the design's risk register —
   write the real one.
5. `uel fmt` before committing; CI enforces canonical layout. Commit
   `uel.lock` — it is the shared memory between agents.

## Writing the graph — the rules that bite

- **Knowns are references, never copies.**
  `knowns { load <- req.STR-014.limit_load }`. If you paste a literal that
  exists elsewhere in the graph, you have created a stale-data bug the
  language was built to prevent. Analysis outputs are addressed with an
  explicit segment: `Other.outputs.name`.
- **Every value carries a unit** (`dimensionless` when truly bare) and may
  carry `± 10 g`, `± 5 %`, or `± cal` (declared-but-uncalibrated).
  Provenance tails are cheap and precious: `= 45 K ± 15 % from "datasheet
  p.2, Te at 25 degC"`.
- **Levels are types** (ADR-0006). EIRP is `22 dBW`, not 22 dB with the
  reference in the name; G/T is `dB/K`; C/N0 is `dBHz`; `dBm` converts by
  −30. Uncertainty on any level is a dB delta (`± 1.5 dB`). One arithmetic
  rule: levels add where linear quantities multiply — `dBW − dB + dB/K −
  db(J/K)` type-checks to `dBHz`. `db(x)` lifts linear→level, `lin(x)` drops
  back; a bare scalar multiplies only plain `dB`.
- **Prefer `core expr` for algebra** — the checker then sees inside the
  formula and a dimensional slip is a compile error, not a wrong margin:

  ```
  core expr {
    let lambda = const.c0 / freq
    let fspl_db = 2 * db(4 * const.pi * max_range / lambda)
    margin_db = eirp_dbw - fspl_db + g_over_t_dbk - db(const.k_B) - db(data_rate) - required_ebn0_db
  }
  ```

  Functions: `sqrt log10 ln exp sin cos abs min max db lin`. Constants:
  `const.pi c0 k_B h g0`. No conditionals or loops — a core that needs them
  is a Python core (JSON on stdin/stdout; read the `si` field; see
  docs/core-protocol.md). `core stub { x = 4 dB }` is a legitimate
  placeholder and is publicly ledgered as one.
- **Expression gotchas** (each cost a real debugging session): identifiers
  may contain hyphens (`STR-014`), so subtraction NEEDS SPACES — `a - b`,
  never `a-b`. After a numeric literal, unit symbols are consumed greedily:
  `3 m / span` divides (3 m) by `span` only because `span` is not a unit —
  when in doubt parenthesize `(3 m)`. Outputs are assigned exactly once, in
  order; `let` names intermediates.
- **Declare what you produce.** A core output not in `outputs { }` cannot be
  consumed and cannot carry staleness. Give outputs their true type
  (`dBi`, `dB/K`, `deg`) — downstream inference depends on it.
- **State the acceptance line in the language, not in prose:**
  `margin_db : dB ± target >= req.LNK-002.min_margin_db`. Violated targets
  red-gate the merge; met-on-the-nominal with the ± band across the line is
  a standing warning you must answer in judgment, not delete.
- **Fences are checked against the value that actually flows.** An envelope
  predicate on a known that references an upstream output is compared, type
  and value, with the producer's locked output. If it fails: widen the fence
  WITH a judgment saying why, or fix the producer — never rename variables
  to dodge the check.
- **Connect at the level that owns the port**; a binding's realization
  inherits its functional identity's connections. Budgets (`budget mass <=
  470 g`) roll up the containment tree mechanically; `contains X x 2` mints
  instance designators (`X#1`, `X#2`) for as-built records.

## Verification: give reviewers reasons, not assertions

Every opaque core should answer for itself (ADR-0008):

```
core python "analysis/wind_loads.py" {
  tool "su2" "8.0.1"                          # version pins are identity
  interface "vendor/model.xml" sha256 "9a41…" # the black box's own definition
}
verify gust_moment against WindLoadsOracle.outputs.gust_moment within 10 %
verify gust_moment monotone with wind_op rising
verify case "test/hotcase.json" within 1 %
```

- `against` cross-checks lock-vs-lock; its best oracle is a one-line `core
  expr` surrogate you write from first principles WITH ITS OWN coefficients
  (an oracle sharing its subject's inputs only confirms arithmetic).
- `monotone` re-runs the core with a perturbed input at build time — it
  catches wrong physics that agrees at the operating point, which a single
  cross-check can never see.
- `case` re-proves a golden input file every build. Generate it by running
  the core once and pinning what it produced, after you believe it.
- A run that breaks its own contract is a FAILED run. Never delete a
  contract to go green; fix the core, fix the oracle, or widen the band
  with a judgment that says why.

## Reviewing another agent's work (zero-trust)

`uel pack <node>` gives you the claim, framing, every input with provenance,
the argument itself (formula, capped source, or interface manifest), contract
verdicts, targets, blast radius, and the author's judgment with doubts. Audit
order: (1) is the intent the right question; (2) is the model choice in
`framing` fit for it; (3) do the knowns' provenances hold; (4) re-derive or
probe the argument; (5) do the doubts admit the real risks? The status
projection's trust ledger tells you where belief is load-bearing: verified by
construction (expr), by contract, or "trusted on the author's word" — start
your skepticism at the third group. Measurements beat models: land test data
with `uel calibrate <file> <dir>`; discrepancies open investigations and every
consumer flips stale mechanically.

## Multi-agent pattern (proven on a real project)

Architect writes the contract: interfaces + requirements + `core stub`
skeletons with nominal values so every consumer is green from minute zero.
Parallel agents then own disjoint files, replacing stubs with real analyses —
the graph (not chat) is the shared memory, and seams are enforced by fences
and types. Finish with an adversarial reviewer using `uel pack` and
perturbation probes, then a calibration pass. Deviating from a contract
nominal is legitimate exactly when your physics says so — flag it, the
machinery will propagate it.

## Never

- Hand-edit `uel.lock` or anything under `out/` (compiled projections).
- Copy a number that exists anywhere in the graph.
- Leave `judgment accepted` prose that contradicts current lock values.
- Silence a diagnostic by renaming, deleting a contract, or widening a
  fence without a judgment.

## Deep references (in this repository / the uel package)

`docs/syntax.md` (normative grammar) · `docs/schema.md` (JSON graph) ·
`docs/core-protocol.md` (python cores + probes) · `docs/decisions/` (why it
is this way) · `docs/spec.md` + `docs/program.md` (the founding documents) ·
`examples/ground-station*` (a full multi-agent design and its 1/10-cost
excursion, locks included).
