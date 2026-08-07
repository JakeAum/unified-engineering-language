# Agent notes — UEL repository

This repository is both the UEL reference implementation (`uel/`) and three
worked designs (`examples/`). UEL is built for you: orient with `uel agent`
(the tool briefs you from its own live tables), and load the operating skill
at `.claude/skills/uel-engineer/SKILL.md` (installable into any project via
`uel skill install <dir>`).

This file is hand-written, because it describes the *reference implementation*
(test suites, conformance, worked examples) rather than a UEL project. The
project-shaped equivalent is generated: `uel harness install --target agents-md
--dir <repo>` emits an `AGENTS.md` whose every claim about the tool comes from
live kernel tables (ADR-0010). The `.claude/` hooks in this repo ARE generated
(`--target claude-code`); do not hand-edit them — `tests/test_harness.py` fails
if they drift from what the generator emits. Re-run
`python3 -m uel harness install --target claude-code --dir . --force` and
commit whenever a kernel change moves the generated text.

## Commands

```sh
pip install -e .                          # zero-dependency; gives you `uel`
python3 -m unittest discover -s tests     # unit tests
python3 -m conformance.runner             # the conformance suite (the gate)
python3 -m uel check examples/<p>         # compile-time pipeline
python3 -m uel build examples/<p>         # run the stale cone; re-verdict targets/contracts
python3 -m uel fmt --check examples/<p>   # canonical layout (CI enforces)
python3 -m uel harness check --target claude-code   # are the generated adapters current?
```

The merge gate (`.github/workflows/ci.yml`) runs all of the above on every
push. Nothing merges on trust.

## Conventions that bite

- Commit `.uel` sources AND `uel.lock`; never hand-edit `uel.lock` or `out/`.
- Knowns are references, never copies; analysis outputs need `.outputs.`.
- In expressions, subtraction needs spaces (`a - b`) — identifiers may
  contain hyphens (`STR-014`).
- Diagnostics carry stable codes + reasons + often verbatim fixes; the
  fixloop conformance kind grades that errors converge when fixes are applied.
- Kernel changes must keep the three examples' locks reproducing: run the
  full gate, and treat `uel stale examples/<p>` reporting anything stale
  after a no-op refactor as a hashing regression.
- Judgments (`accepted "…" doubts "…"`) must match current lock values;
  doubts are the risk register, not boilerplate.

## Map

`uel/` kernel (see `docs/boot/architecture.md` for the module table) ·
`docs/` spec, program, syntax, schema, core protocol, ADRs ·
`conformance/` + `tests/` the graders · `examples/` apache-one (vertical
slice), ground-station (multi-agent design), ground-station-lc (1/10-cost
excursion — same LinkMargin formula, hash-provably).
