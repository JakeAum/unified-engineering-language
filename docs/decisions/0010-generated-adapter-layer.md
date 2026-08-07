# ADR-0010 — The generated adapter layer: `uel harness install`

*Status: accepted · v0.6 · 2026-08-07 · extends ADR-0002 (zero dependencies) and
the v0.5 agent-native surface (`uel agent`, `uel skill`)*

## Intent

UEL is positioned as a harness-agnostic **exoskeleton**: the fast mechanical
oracle that agentic harnesses call, the way `rustc` and `cargo test` are what
made coding agents good at Rust. We are deliberately not building an agent
harness — the ones that exist are excellent and improving faster than we could
follow. We slot into them.

That leaves exactly one seam to design: the layer where a harness-agnostic
kernel meets a specific harness's reflexes. v0.5 built the *substance* of that
seam — `uel agent` briefs the model from live kernel tables, `uel skill` ships
the operating skill — but a briefing an agent must remember to ask for is worth
much less than a diagnostic that arrives, unbidden, in the same context window
as the edit that caused it. The highest-value integration in the whole system is
a PostToolUse hook: it turns a slow oracle (run at merge) into a fast one (run
on a keystroke), and it is four lines of harness configuration away.

The danger is equally clear. Anything hand-written into `.claude/` is a
liability that goes stale the moment Claude Code changes shape — and it will,
next quarter. The v0.1.2 harness (since removed) was exactly this: prose about
UEL, typed into templates, drifting from the kernel from the day it was written.

## Decision

**`uel harness install --target claude-code|agents-md [--dir .] [--force]`**,
plus `uel harness check` and `uel harness show`. One architectural rule governs
everything under it:

> **Substance portable, reflexes local.** Nothing below the adapter layer knows
> a harness exists, and nothing in the adapter layer is hand-written.

Operationally that splits into four commitments.

**1. The templates know the harness; the substitutions know UEL.** A template
under `uel/adapters/<target>/` may encode only harness mechanics: where a file
goes, what JSON a hook is handed on stdin, which exit code feeds text back to
the model, what `CLAUDE_PROJECT_DIR` means. Every token about UEL — the command
names, their one-line descriptions, the diagnostic-code families and their
count, the loop, the syntax card, the expression functions and constants, the
level units, the node kinds, the names of the manifest and the lock — is
substituted at generation time from a live kernel table:

| token source | live table |
|---|---|
| commands, their help text, their options | `cli.build_parser()` (the argparse tree itself) |
| code families, counts | `diagnostics.CODES` grouped into bands, labelled from `agentdoc.FAMILIES` |
| functions, constants, levels, node kinds | `expr.FUNCTIONS`/`CONSTS`, `units.UNITS`, `graph._KIND_MAP` |
| file vocabulary | `project.MANIFEST` / `LOCK` / `SOURCE_SUFFIX` / `COMPILE_TIME_INPUTS` |
| the briefing, quoted verbatim | `agentdoc.briefing()` |
| guidance with no table behind it | named sections of the packaged `skill/SKILL.md` |

`cli.py`'s parser construction was extracted into `build_parser()` for exactly
this reason: the CLI surface is now a table the kernel can read about itself.
Adding a subcommand updates `uel agent`, the emitted `AGENTS.md`, and the
session brief with no prose edit anywhere — the `harness` command itself was the
first thing to arrive that way.

The rule is enforced, not merely stated. `tests/test_harness.py` fails if any
template contains a literal live subcommand name, a diagnostic-code band, or a
project filename. If you type `uel check` into a template, CI stops you. That
test is the load-bearing part of this ADR.

**2. An adapter is a directory of data.** `uel/adapters/<target>/adapter.json`
lists templates, destinations, executable bits, which files are JSON-merged, and
whether the packaged skill rides along. There is no per-target Python in the
kernel. Adding a harness adds a directory; removing one is `rm -r`. Each adapter
is budgeted under 200 lines and a test enforces it (claude-code is 193,
agents-md 70). Disposability is a measured property, not an aspiration.

**3. Merge, never clobber.** `.claude/settings.json` is the user's file. The
installer appends its hook groups only where an identical command is not already
registered; foreign events, foreign matcher groups within the same event, and
every non-hook key survive untouched. Unparseable JSON is left strictly alone
and reported. Re-installing is a byte-level no-op. Generated files that a human
has since edited are kept, and reported, unless `--force`.

**4. Drift is a test failure.** This repository installs its own adapter, and
`uel harness check` compares every installed artifact against what the generator
currently emits. A kernel change that alters generated content and is not
followed by a regenerate-and-commit fails CI. This is the v0.5 skill-drift trick
generalized: *the reason it is safe to throw an adapter away is that nobody is
allowed to hand-maintain one.*

### What is emitted

`claude-code` — `.claude/hooks/uel-check.py` (PostToolUse: on any edit to a
compile-time input, locate the *enclosing* project by walking up to its
manifest, run `uel check --json`, and print code + message + span + reason +
verbatim fix to stderr, exit 2); `.claude/hooks/uel-agenda.sh` (SessionStart:
the ranked work brief for up to three projects, deepest-last); merged hook
wiring in `.claude/settings.json`; and the packaged skill via the existing
`skill_install` machinery, reused rather than duplicated.

`agents-md` — a vendor-neutral `AGENTS.md` whose every claim about the tool is
generated, including the full `uel agent` briefing quoted verbatim, for harnesses
that read the convention and for humans reviewing a repository cold.

### Degrading toward work that has not landed

The session brief wants the *ranked* queue, which lives in economics work
proceeding concurrently. Naming a command that may not exist is a real hazard,
so the adapter carries a **ladder** — `stale --rank`, then `agenda`, then plain
`stale` — and the emitted hook **probes each rung at runtime** against the
kernel actually installed, using it only if `--help` confirms it. The last rung
is a declared floor the generator asserts against the live CLI table and refuses
to emit without. `doctor` is handled the same way: probed, surfaced when
present, silent when absent.

Runtime probing rather than generation-time detection is deliberate. An adapter
outlives the kernel version that generated it — users upgrade, downgrade, and
run one checkout's hooks against another's kernel. Probing also keeps the
artifact stable when the sibling command lands, so the drift test does not fire
on work this adapter did not do.

### No new diagnostic codes

The UEL11xx band is reserved and unused. The code registry is the *graph
checker's* stable API: codes are cited in conformance expectations, in agent
muscle memory, and in every `--json` consumer. Adapter installation is not graph
checking, and no `.uel` source can trigger it. Minting codes nothing can emit
would dilute the registry — the load-bearing-or-dead rule of ADR-0008, applied
to ourselves. `uel harness check` reports drift as plain text and an exit code.

## Consequences

- The keystroke gate exists: an agent editing a `.uel` file in a repo with this
  adapter installed gets structured diagnostics back before it moves on. This is
  the single highest-leverage thing the exoskeleton can do, and it now costs one
  command to turn on.
- Three small kernel changes serve generation and stand on their own:
  `cli.build_parser()`, `project.MANIFEST`/`LOCK`/`SOURCE_SUFFIX`/
  `COMPILE_TIME_INPUTS`, and `agentdoc.FAMILIES`/`SKILL_REL` promoted from
  private to live tables. A code minted in an unlabelled band now fails a test.
- Emitted hooks are stdlib-only and never assume a global install: both detect
  the entry point, falling back to `python3 -m uel` with the repository on
  `PYTHONPATH`, so a source checkout that was never pip-installed still works.
  Both are silent no-ops when no kernel answers — a repository must never be
  broken by its own tooling.
- This repository installs the `claude-code` adapter and keeps its **hand-written
  root `AGENTS.md`**, which describes the reference implementation (test suites,
  conformance, worked examples) rather than a UEL project. The drift test
  therefore gates the `.claude/` artifacts; the `agents-md` target is graded by
  generation tests and by installing into scratch repositories. Honest asymmetry,
  recorded rather than papered over.
- Harness APIs will change and these adapters will break. That is priced in: the
  fix is to edit a template or delete a directory, and the drift test tells you
  the moment the emitted content stops matching the kernel.

## Alternatives rejected

- **Hand-written `.claude/` in the repo, no generator.** The v0.1.2 approach.
  It works for exactly one kernel version and one harness version, and nothing
  detects when it stops being true.
- **Generation-time detection of sibling commands.** Simpler code, but bakes
  "this kernel had `--rank` on 2026-08-07" into a file that will be run against
  other kernels, and churns the drift test whenever unrelated work lands.
- **A `uel-harness` plugin package.** Would keep the kernel clean, but violates
  ADR-0002's single-artifact posture and puts the adapter on a different release
  cadence than the tables it must track — which is precisely how drift starts.
- **Emitting a Claude Code *skill* per target instead of hooks.** Skills are
  pulled; hooks are pushed. The whole value here is the diagnostic the agent did
  not think to ask for. The skill still ships — the two are complementary, and
  the claude-code adapter installs both.
