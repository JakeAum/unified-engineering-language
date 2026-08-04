# The conformance suite

This is the artifact all kernel work is graded against (program §2.2). The
implementation is its first conforming instance, not its definition: **cases are
authored from the spec's text**, and a case that encodes an implementation quirk
is a defect in the suite.

Run: `python3 -m conformance.runner` (zero dependencies; `-k substring` filters).

| Kind | Grades | Case shape |
|---|---|---|
| `schema/` | canonical round-trip of graph documents (Phase 1) | `*.json` graph docs; `invalid_*` must be rejected |
| `parse/` | surface syntax → expected diagnostics | `X.uel` + `X.expect.json` (codes, optional lines) |
| `units/` | dimension checking against the stdlib | same shape, resolved in a temp project |
| `fmt/` | formatter idempotence + AST preservation | `X.uel`, optional `X.golden` |
| `fixloop/` | seeded errors converge to clean under the **mechanical** fix driver (`fixdriver.py` applies `fix.replace` verbatim — no model, no judgment) | project dir |
| `check/` | full-project compile-time verdicts | project dir + `expected.json` |
| `derisk/` | **R1 pair set** (spec §10.1): eleven real cross-domain analysis pairs; each must get the physically right verdict — clean composition and correct rejection count equally | project dir + `expected.json` |

Matching discipline: expected diagnostics must appear (by code, and line when
given); unexpected **errors** fail the case; extra warnings/infos are allowed —
advisory chatter must never be load-bearing.

Scheduler/staleness semantics need orchestration (build → edit → rebuild), so
they are graded in `tests/` (`test_staleness_50.py`, `test_scheduler_contract.py`,
`test_calibration.py`, `test_redteam.py`) — same CI gate, different harness.
