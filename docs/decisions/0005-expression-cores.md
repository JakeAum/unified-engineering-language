# ADR-0005 — Expression cores: the formula moves inside the language

*Status: accepted · v0.2 · 2026-08-05 · extends spec §3.2 (shell-and-core)*

## Intent

Close the largest gap the v0.1 retrospective named: the kernel typed the shell
of every analysis — units, references, fences, staleness — and *trusted the
core*. Inside `link_margin.py` the FSPL formula could be wrong and nothing in
the language would know. Most cores in the three worked examples were under
thirty lines of arithmetic over their knowns; that arithmetic belongs under the
checker.

## Decision

Add two core kinds beside `python`:

    core expr {                       core stub {
      let lambda = const.c0 / freq      g_over_t_dbk = 29.6 dB/K
      margin_db = ...                 }
    }

- **`core expr`** bodies are statements of arithmetic (`+ - * / ^`, `sqrt`,
  `log10`, `ln`, `exp`, `sin`, `cos`, `abs`, `min`, `max`, `db`, `lin`) over
  knowns, params, `const.*` physical constants, `let` intermediates, and
  earlier outputs. The checker **infers every expression's type** — dimension
  plus level flag (ADR-0006) — before anything runs; a formula whose result
  type disagrees with its declared output unit is a compile error naming both
  sides (UEL0310–0312).
- **Evaluation is kernel-side interval arithmetic** over (lo, nominal, hi)
  triples seeded from the knowns' declared bands. The output band is a
  **guaranteed worst-case enclosure**, not a 1σ RSS. Cores that need
  statistical bookkeeping, iteration, geometry, or file artifacts remain
  Python cores — shell-and-core is unchanged for them, and geometry nodes are
  expr-forbidden because they must assert topology.
- **The canonical formatted body is the core's content-addressed identity**
  (`Core.text`): a whitespace re-flow is not a change; an edited coefficient
  invalidates exactly its cone.
- **`core stub`** is the ground-station org pattern — executable placeholders
  carrying declared nominals so every consumer is green from minute zero —
  promoted into the language. Stubs run like expr cores, are announced on
  every check (UEL0807), and are ledgered in the status projection.

## Consequences

- The units checker now covers the *interior* of migrated analyses: in the
  ground-station examples, forgetting `db()` around a data rate is a compile
  error, not a wrong margin (conformance `check/expr_dim_catch`).
- Uncertainty semantics changed for migrated nodes: worst-case enclosures are
  wider than the v0.1 hand-RSS numbers (ground-station t_sys ±12.5 K → ±25 K).
  This is declared in the affected judgments; RSS remains available via
  Python cores.
- Nominal values reproduced to sub-millidB in migration, except where the
  formula got *more* right: Boltzmann now enters as `db(const.k_B)` exactly,
  retiring the 228.6 contract constant (−0.0009 dB on C/N0).
- The evaluator is deliberately type-blind: after inference proves legality,
  level arithmetic *is* plain arithmetic on canonical dB numbers.

## Revisit

When a real project needs first-class distributions (not enclosures), or when
expression bodies grow conditionals — both are v0.3 questions and both must
not arrive as Python-in-disguise.
