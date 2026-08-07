# The tool surface is an API — stability contract

*Normative for v0.6 onward. Companion to `docs/core-protocol.md` (which governs the
shell↔core boundary); this document governs the **tool↔caller** boundary.*

## Why this exists

UEL's whole position is that it is the **oracle**, not the agent: a fast, cheap,
mechanical check that some other system — an agentic harness, a CI runner, a
human at a terminal — calls and believes. That only works if the surface it
presents holds still.

The failure mode is specific and silent. An agent prompted (or, later, trained)
against `uel check --json` learns the shape of what comes back. If a field is
renamed, a code's meaning drifts, or an exit code changes character, nothing
crashes — the caller quietly misreads the answer and proceeds with confidence.
A compiler that lies about *how* it says no is worse than one that cannot say no
at all.

So: **the CLI surface, the JSON schema, the exit codes, and the diagnostic code
registry are a public API.** They are versioned, they are tiered, and they are
enforced by conformance cases rather than by intention.

## Who the callers are

Three, with different needs, and the contract serves all three:

| Caller | Reads | Needs above all |
|---|---|---|
| Agentic harness (hook, skill, MCP) | `--json` | stable field names; fixes it can apply without judgment |
| CI / merge gate | exit code | to distinguish *rejected* from *broken* |
| Human at a terminal | rendered text | prose that explains the physics |

Only the first two are under this contract. Human-readable rendering is
explicitly **not** stable — see Tier 3.

## Tiers

**Tier 1 — Frozen.** Changes only with an edition bump and an ADR.

- **Diagnostic code identity.** `UEL0501` means what it meant the day it was
  minted, forever. A retired code is never reused for a different meaning — it
  is retired and left retired, the way a tail number is never reissued.
- **Exit-code semantics** (below).
- **The JSON envelope shape** — the `uel` header block and the top-level keys.
- **Severity vocabulary**: `error`, `warning`, `info`.

**Tier 2 — Additive only, within an edition.** New things may appear; existing
things do not change meaning or disappear.

- CLI subcommands and flags.
- Fields inside `result` and inside a diagnostic object.
- The diagnostic code *set* — new codes may be minted at any time. **A caller
  must therefore treat an unrecognized code as a valid diagnostic of its stated
  severity, never as a parse failure.**
- Entries in the units, models, claims, and constants tables.

**Tier 3 — Not stable. Do not parse.**

- Rendered human output: wording, colour, ordering, box drawing.
- Diagnostic `message` and `reason` prose. These are deliberately edited to
  teach better — that is the fix-loop product surface and it must stay free to
  improve. **Match on `code`, never on message text.**
- Wall-clock timings, node iteration order where not explicitly documented.

The split is the point: the *identity* of a complaint is frozen so machines can
rely on it, and the *explanation* of a complaint stays liquid so humans and
agents keep getting a better one.

## The JSON envelope

Every `--json` invocation emits exactly one JSON object on stdout:

```json
{
  "uel": {
    "protocol": 1,
    "kernel": "0.6.0",
    "edition": "2026",
    "command": "check",
    "ok": false
  },
  "diagnostics": [ /* diagnostic objects, see below */ ],
  "result": { /* command-specific, Tier 2 */ }
}
```

- `protocol` is this contract's version. It increments **only** on a Tier 1
  break. A caller that understands protocol *N* must refuse, loudly, to
  interpret protocol *N+1* rather than guess.
- `kernel` and `edition` are informational provenance, not dispatch keys.
- `ok` mirrors "no error-severity diagnostics" — the same condition as exit 0.
- `diagnostics` is always present, possibly empty. `result` is always present,
  possibly `{}`.

Nothing but this object goes to stdout under `--json`. Progress chatter,
warnings about the run itself, and anything else humans might want go to
**stderr**, so a caller can pipe stdout into a parser unconditionally.

### Diagnostic objects

The shape already produced by `Diagnostic.to_obj()`:

```json
{
  "code": "UEL0501",
  "title": "envelope not covered",
  "severity": "error",
  "message": "'WingFlutter' assumes root_moment in [0, 400 N*m], but ...",
  "span": {"file": "model/structure.uel", "line": 42, "col": 3},
  "reason": "composition rule (spec §2.5): a guarantee must cover the assumption it feeds",
  "fix": {"hint": "...", "replace": "...", "span": {...}},
  "related": [{"note": "guarantee declared here", "span": {...}}]
}
```

`code`, `severity`, `message`, and `span` are always present. `title`, `reason`,
`fix`, and `related` are present when they exist.

### The `fix` contract

A `fix` carrying `replace` is a **mechanically applicable** edit: substituting
`replace` for the text at `fix.span` (defaulting to the diagnostic's span) is
correct without judgment. This is a hard promise, and it is what lets a fix loop
converge without a model in the loop.

A `fix` carrying only `hint` requires judgment and must not be applied blindly.

Callers may apply `replace` fixes automatically. If a `replace` fix is ever
wrong, that is a kernel bug of the highest severity, not a caller error.

## Exit codes

The distinction that matters most to an agent, and the one most CLIs get wrong:

| Code | Meaning | What a caller should do |
|---|---|---|
| `0` | Clean. No error-severity diagnostics. | Proceed. |
| `1` | **The model was rejected.** The tool ran correctly and the graph is wrong. | Read the diagnostics and fix the model. |
| `2` | **Usage error.** Bad arguments, unknown subcommand. | Fix the invocation. |
| `3` | **The tool could not run.** Unreadable project, unparseable lock, internal error. | Fix the environment. Do *not* edit the model. |

`1` and `3` are the load-bearing pair. "Your beam fails at limit load" and "I
couldn't open the lockfile" are opposite instructions, and a caller that cannot
tell them apart will either thrash on a healthy model or silently ignore a real
rejection. Anything that is not a judgment about the graph is a `3`.

## Deprecation

Within an edition, nothing in Tier 1 or Tier 2 is removed. When something must
go:

1. It keeps working, and emits an `info` diagnostic naming the replacement.
2. It stays that way for a full minor version at minimum.
3. Removal happens only at an edition boundary, with an ADR, and is listed in
   the edition's migration notes.

Diagnostic codes are never removed at all — a rule that stops firing keeps its
registry entry, marked retired, so that historical locks, projections, and
dossiers stay readable. The graph is content-addressed and long-lived; its
diagnostics have to be too.

## How this is enforced

A contract graded by good intentions is not a contract. Enforcement:

- **Envelope conformance cases** assert the header block and top-level keys for
  every `--json`-capable command.
- **The code registry is append-only**, checked by a test that fails if a code's
  registered title changes or an existing code disappears.
- **Exit-code cases** cover all four codes, including at least one genuine `3`
  (a deliberately corrupted lock) to prove `1` and `3` are actually distinct in
  practice and not merely in this document.

## Current conformance — honest ledger

This document is normative as of v0.6, and the kernel does **not** yet fully meet
it. Recorded plainly, because an aspirational contract that pretends to be a
real one is the exact failure this document exists to prevent:

| Clause | State |
|---|---|
| Diagnostic object shape | **Met.** `Diagnostic.to_obj()` already emits it. |
| `fix.replace` mechanical applicability | **Met.** Proven by the fix-loop conformance case. |
| Code registry with titles | **Met.** `CODES` in `uel/diagnostics.py`. |
| Append-only registry test | **Met.** `tests/test_api_contract.py` against a pinned snapshot; proven to catch both removal and title drift. |
| JSON envelope | **Built, not wired.** `uel/api.py:envelope()` implements and tests it; `check --json` still emits a bare diagnostics array with no header block. |
| `--json` on every command | **Not built.** Only `check` has it. |
| Exit code `3` distinct from `1` | **Built, not wired.** `uel/api.py:guard()` implements and tests the split, including the crash-must-not-read-as-a-verdict case; no command routes through it yet. |
| stdout/stderr discipline | **Partial.** Some commands print progress to stdout. |
| Envelope + exit-code conformance cases | **Unit-tested** (`tests/test_api_envelope.py`); no end-to-end conformance cases until the commands are wired. |

Closing this table is the definition of done for the machine-surface work.
