# ADR-0006 — Adoption is a feature: `uel init` and the agent harness

*Status: accepted · 2026-08-05 · executes gap-analysis move 1 for repositories other than this one*

## Intent

ADR-0005 gave the graph an economics scheduler; `docs/org/user-org-loop.md`
gave *this* repository a standing loop. Neither is reachable by anyone else:
adopting UEL meant reverse-engineering `examples/apache-one`, hand-copying a
runbook, and wiring your own gates. That is a real problem for the program's
own metrics — **program §6.3's adoption-refusal kill criterion is untestable
until an adopter outside this repository exists**, and spec §10.2's leverage
claim is only falsifiable on someone else's hardware. A kernel nobody can
start using in one command stays in one repository.

## Framing

- Model: scaffold two layers in one command — the **project** (manifest,
  starter model, core, campaign template, calibration directories) and the
  **harness** (the affordances an agent org needs to work that project with no
  shared context).
- `assume harness_is_thin because "the durable asset is the graph and the
  protocol, not any vendor's hook format"` — hence `AGENTS.md` as the
  vendor-neutral boot document, `.claude/` as one adapter, `--harness none`
  for anyone who wants neither.
- Boundary: `uel init` writes files and nothing else. It does not install, run
  git, phone home, or edit anything it did not create.

## Knowns

The harness, and what each piece buys:

| file | role |
|---|---|
| `AGENTS.md` / `CLAUDE.md` | boot context: layout, the five commands, what the graph guarantees **and what it never will** |
| `.claude/skills/uel-loop/SKILL.md` | the iteration protocol, invocable by name |
| `.claude/hooks/uel-check.py` | PostToolUse: `uel check` on every `.uel` edit; on errors, exit 2 feeds the diagnostics straight back to the agent that made the edit |
| `.claude/hooks/uel-agenda.sh` | SessionStart: the agenda prints into a waking session's context |
| `.claude/settings.json` | hook registration, **merged** — foreign hooks and permissions preserved |
| `.github/workflows/uel-gate.yml` | the merge gate: check, fmt, build, and lock-is-current |
| `docs/org/loop.md`, `loop-log.md` | the standing protocol and its cost denominator |

The compile hook is the load-bearing idea. Compile time is seconds and runs no
solver (spec §4.4), which makes it cheap enough to fire on a keystroke rather
than only at merge — so a dropped unit, a broken fence, or an unresolved
reference is corrected in the same breath it was written, by the agent that
wrote it. The merge gate becomes a *keystroke* gate, and the structured
diagnostics stop being a report and become the fix loop (spec Phase 2's
premise, wired into the harness).

Safety properties, each pinned by `tests/test_scaffold.py` (17 tests): the
scaffolded model checks clean, builds, is formatter-canonical (its own CI
would pass on the first push), and yields a useful day-one agenda — an
unjudged result, a ranked measurement (`± cal` on the load case), and a live
margin. The hook blocks a seeded fence violation with code, reason, and
location; stays silent on clean edits, non-model edits, foreign files, and
garbage stdin; and is a **no-op when the kernel is not installed**. The
settings merge preserves foreign hooks, is idempotent, and refuses to touch
unparseable JSON. Existing files are never clobbered without `--force`.

## Derivation

`uel/templates/*.tmpl` (package data, rendered by `{{TOKEN}}` substitution —
not `str.format`, since the templates are full of literal braces),
`uel/scaffold.py`, and `uel init [path] [--name] [--harness claude|none]
[--force]`. Harness files land at the repository root and project files at the
target path, so `uel init hardware/` wires `hardware` through the CI, the
hooks, and the boot docs correctly.

Writing the templates surfaced a genuine defect in the deliverable: the first
draft was not formatter-canonical, so a scaffolded repo's own `uel fmt
--check` would have failed on its first CI run. Fixed, and pinned by a test
that formats the templates and demands a fixpoint.

## Judgment

Accepted. The scaffold is deliberately opinionated — a starter model with a
declared fence, a `± cal` quantity, an uncertainty-carrying core, and a
`judgment pending` — because the fastest way to teach the method is to hand
someone a graph that already has the shape and let the agenda pull them
forward. Doubts, honestly held: (1) the starter model is a structural example,
and an adopter in electronics or fluids will delete more than they keep — the
shape generalizes, the content does not; (2) `.claude/` is one vendor's hook
format, and if the ecosystem converges elsewhere that adapter is churn (the
`AGENTS.md` split is the hedge); (3) the CI template pins UEL to `@main`,
which is wrong for anyone who needs reproducibility — the comment says so, but
a pin nobody edits is a footgun; (4) none of this has been run by an adopter
who is not us, which is precisely the thing it exists to enable and therefore
the next real evidence to collect.
