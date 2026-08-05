# Agent notes — UEL repository

This repository is both the UEL reference implementation (`uel/`) and three
worked designs (`examples/`). UEL is built for you: orient with `uel agent`
(the tool briefs you from its own live tables), and load the operating skill
at `.claude/skills/uel-engineer/SKILL.md` (installable into any project via
`uel skill install <dir>`).

## Commands

```sh
pip install -e .                          # zero-dependency; gives you `uel`
python3 -m unittest discover -s tests     # unit tests
python3 -m conformance.runner             # the conformance suite (the gate)
python3 -m uel check examples/<p>         # compile-time pipeline
python3 -m uel build examples/<p>         # run the stale cone; re-verdict targets/contracts
python3 -m uel fmt --check examples/<p>   # canonical layout (CI enforces)
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
