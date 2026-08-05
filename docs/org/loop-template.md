# The loop, parameterized

The standing iteration protocol has one canonical source:
**[`uel/templates/loop.md.tmpl`](../../uel/templates/loop.md.tmpl)**, shipped as
package data and rendered into any repository by `uel init` (ADR-0006). Its
companion, `uel/templates/skill.md.tmpl`, is the same protocol in invocable
form (`.claude/skills/uel-loop/`).

Four parameters distinguish one instance from another:

| parameter | meaning | this repo's instance |
|---|---|---|
| `{{NAME}}` | program name | UEL / apache-one |
| `{{PROJECT_REL}}` | where the model lives | `examples/apache-one` |
| `{{BRANCH_PREFIX}}` | where work lands | `claude/user-org-` |
| cost log | the leverage denominator | `docs/org/loop-log.md` |

Everything else is invariant, and deliberately so: read the agenda, take the
top item, do it completely, gate it, judge it, record what it cost, file what
hurt. That sequence is the program's operating claim in procedural form — a
loop that measures itself is the only kind that can be shown to compound.

## The instances

- **This repository's user org** — [`user-org-loop.md`](user-org-loop.md),
  working `examples/apache-one`. It predates the template and carries extra
  boundary rules specific to a user org living inside the tool's own
  repository (never modify `uel/`, push only `claude/user-org-*`). Those rules
  are *this* instance's, not the template's: an adopter owns their whole repo
  and needs no such wall.
- **Any adopter** — rendered to `docs/org/loop.md` by `uel init`.

Amend the template when the *protocol* changes; amend an instance when its
program does.
