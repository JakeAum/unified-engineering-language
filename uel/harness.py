"""`uel harness install` — the generated adapter layer (ADR-0010).

UEL is an exoskeleton, not a harness: agentic harnesses call it the way a coding
agent calls `rustc` and `cargo test`. Everything below this module is
harness-agnostic, and this module is the only place that knows a harness exists.

It does not *author* what it emits. Every sentence an adapter says about UEL is
substituted from a live kernel table — the argparse tree in `cli.build_parser`,
`diagnostics.CODES`, `expr.FUNCTIONS`/`CONSTS`, `units.UNITS`, `graph._KIND_MAP`,
`project.MANIFEST`/`LOCK`, the packaged `skill/SKILL.md`, `agentdoc.briefing()`.
The templates under `uel/adapters/<target>/` know only their harness's mechanics:
where a file goes, what JSON a hook is handed, which exit code feeds text back.

**Substance portable, reflexes local.** An adapter is a directory of data —
`adapter.json` plus templates — so adding a harness adds no Python to the kernel
and removing one is `rm -r`. `uel harness check` is the drift gate: an installed
adapter that no longer matches what the generator emits is a bug, and it fails
CI (tests/test_harness.py), which is what makes adapters safe to throw away.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import EDITION, SCHEMA_VERSION, __version__
from .diagnostics import CODES
from .project import COMPILE_TIME_INPUTS, LOCK, MANIFEST, SOURCE_SUFFIX

ADAPTERS = Path(__file__).resolve().parent / "adapters"

# Harness-side knobs (how loud an adapter is allowed to be), not kernel facts.
MAX_PROJECTS = 3  # projects a session-start brief will survey
MAX_LINES = 14  # lines of brief per project
MAX_DIAGNOSTICS = 12  # errors quoted back into an edit's context

# The loop's *shape* is a decision; every command in it is verified against the
# live CLI table and its one-line why is the tool's own --help text. A None rung
# is a human step with no command.
LOOP: tuple[tuple[str | None, str], ...] = (
    ("check", ""),
    (None, "fix every diagnostic — each carries a stable code, a reason, and often a verbatim fix"),
    ("build", ""),
    (None, "record judgment WITH doubts: what the numbers say, and what would change your mind"),
    ("fmt", ""),
    (None, f"commit sources AND {LOCK} — never hand-edit {LOCK} or anything under out/"),
)

# The ranked work brief, best rung first. Rungs above the floor are commands that
# concurrent kernel work may or may not have landed (`stale --rank`, `agenda`);
# the emitted hook PROBES for each at runtime rather than assuming, so an adapter
# generated today keeps working against a kernel from either side of that change.
BRIEF_LADDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("stale", ("--rank",)),
    ("agenda", ()),
    ("stale", ()),
)
BRIEF_FLOOR = ("stale", ())  # must exist in the live table or the generator refuses
# Agent-relevant commands that may not exist yet: named, probed, never assumed.
OPTIONAL_COMMANDS = ("doctor",)


class HarnessError(RuntimeError):
    """The generator refuses to emit an adapter it cannot ground in a live table."""


# --------------------------------------------------------------------------- #
# live kernel tables
# --------------------------------------------------------------------------- #

def _cli():
    from .cli import build_parser

    return build_parser()


def commands() -> dict[str, str]:
    """Every subcommand the kernel actually exposes, name -> its own help text."""
    _, sub = _cli()
    helps = {a.dest: (a.help or "") for a in getattr(sub, "_choices_actions", [])}
    return {name: helps.get(name, p.description or "") for name, p in sub.choices.items()}


def options(command: str) -> set[str]:
    """Every option string a subcommand accepts, live."""
    _, sub = _cli()
    parser = sub.choices.get(command)
    if parser is None:
        return set()
    return {opt for action in parser._actions for opt in action.option_strings}


def supports(command: str, *opts: str) -> bool:
    if command not in commands():
        return False
    have = options(command)
    return all(o in have for o in opts)


def code_families() -> list[tuple[str, str, int]]:
    """(band, label, count) derived from the live CODES registry. Labels come from
    the kernel's own family table; an unlabelled band is a test failure, not prose
    invented here."""
    from .agentdoc import FAMILIES

    labels = dict(FAMILIES)
    counts: dict[str, int] = {}
    for code in CODES:
        counts[code[:5] + "xx"] = counts.get(code[:5] + "xx", 0) + 1
    return [(band, labels.get(band, "(unlabelled band)"), n) for band, n in sorted(counts.items())]


def skill_section(title: str) -> str:
    """A section of the packaged operating skill, verbatim — one source of truth
    for guidance that has no table to generate it from."""
    from .agentdoc import SKILL_DIR

    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if out:
                break
            if line[3:].strip().lower().startswith(title.lower()):
                out.append("")  # marker: we are inside the section
            continue
        if out:
            out.append(line)
    body = "\n".join(out).strip("\n")
    if not body:
        raise HarnessError(f"packaged skill has no '{title}' section to quote")
    return body


def loop_block() -> str:
    cmds = commands()
    lines, n = [], 0
    for name, prose in LOOP:
        n += 1
        if name is None:
            lines.append(f"{n}. {prose}")
            continue
        if name not in cmds:
            raise HarnessError(f"the loop names `{name}`, which this kernel does not expose")
        lines.append(f"{n}. `{tool()} {name} <dir>` — {cmds[name]}")
    return "\n".join(lines)


def loop_oneline() -> str:
    cmds = commands()
    parts = [f"{tool()} {n}" if n else p.split(" —")[0].split(":")[0]
             for n, p in LOOP if n is None or n in cmds]
    return "loop: " + " -> ".join(parts)


def command_block() -> str:
    return "\n".join(f"- `{tool()} {name}` — {help_}" for name, help_ in sorted(commands().items()))


def brief_ladder() -> tuple[str, str]:
    """(pipe-encoded ladder for the emitted hook, human display of the same).

    The floor rung is asserted against the live table: the generator will not emit
    a work brief it cannot guarantee resolves to something.
    """
    if BRIEF_FLOOR[0] not in commands():
        raise HarnessError(f"no work-queue command in this kernel (expected `{BRIEF_FLOOR[0]}`)")
    rungs = [" ".join((name, *opts)) for name, opts in BRIEF_LADDER]
    return "|".join(rungs), " then ".join(f"`{tool()} {r}`" for r in rungs)


# --------------------------------------------------------------------------- #
# substitutions — every token is a live table read, never a literal
# --------------------------------------------------------------------------- #

_TOOL_CACHE: list[str] = []


def tool() -> str:
    """The program name, from the live parser — never a literal, even this one."""
    if not _TOOL_CACHE:
        ap, _ = _cli()
        _TOOL_CACHE.append(ap.prog)
    return _TOOL_CACHE[0]


def tokens() -> dict[str, str]:
    from .agentdoc import SKILL_REL, briefing
    from .graph import _KIND_MAP

    ladder, ladder_display = brief_ladder()
    check_argv = ["check", "--json"] if supports("check", "--json") else ["check"]
    cmds = commands()
    orient = next((c for c in ("agent", "check") if c in cmds), BRIEF_FLOOR[0])
    return {
        "ORIENT": orient,
        "SKILL_REL": str(SKILL_REL / "SKILL.md"),
        "TOOL": tool(),
        "VERSION": __version__,
        "EDITION": EDITION,
        "SCHEMA": SCHEMA_VERSION,
        "MANIFEST": MANIFEST,
        "LOCK": LOCK,
        "SUFFIX": SOURCE_SUFFIX,
        "WATCHED_JSON": json.dumps(sorted(COMPILE_TIME_INPUTS)),
        "CHECK_ARGV_JSON": json.dumps(check_argv),
        "MAX_PROJECTS": str(MAX_PROJECTS),
        "MAX_LINES": str(MAX_LINES),
        "MAX_DIAGNOSTICS": str(MAX_DIAGNOSTICS),
        "BRIEF_LADDER": ladder,
        "BRIEF_LADDER_DISPLAY": ladder_display,
        "OPTIONAL_COMMANDS": " ".join(OPTIONAL_COMMANDS),
        "LOOP": loop_block(),
        "LOOP_ONELINE": loop_oneline(),
        "COMMANDS": command_block(),
        "CODE_COUNT": str(len(CODES)),
        "CODE_FAMILIES": "\n".join(f"- `{band}` ({n}) — {label}" for band, label, n in code_families()),
        "KINDS": " ".join(sorted(_KIND_MAP)),
        # expression functions/constants and the level vocabulary reach adapters
        # inside BRIEFING, which is `uel agent` verbatim — one path, not two.
        "NEVER": skill_section("Never"),
        "BRIEFING": briefing(commands=sorted(cmds)).rstrip("\n"),
    }


def render(text: str, subs: dict[str, str]) -> str:
    """`{{TOKEN}}` substitution — not str.format, because adapters are full of
    literal braces (JSON, Python, shell)."""
    for key, value in subs.items():
        text = text.replace("{{" + key + "}}", value)
    return text


# --------------------------------------------------------------------------- #
# adapters: a directory of data, and nothing else
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Artifact:
    rel: str
    text: str
    executable: bool = False
    merge: bool = False  # JSON-merge into whatever is already there


@dataclass(frozen=True)
class Target:
    name: str
    dir: Path

    @property
    def spec(self) -> dict:
        return json.loads((self.dir / "adapter.json").read_text(encoding="utf-8"))

    @property
    def description(self) -> str:
        return str(self.spec.get("description", ""))

    def artifacts(self) -> list[Artifact]:
        subs, spec = tokens(), self.spec
        out = [Artifact(f["dest"], render((self.dir / f["template"]).read_text("utf-8"), subs),
                        bool(f.get("executable")))
               for f in spec.get("files", [])]
        out += [Artifact(f["dest"], render((self.dir / f["template"]).read_text("utf-8"), subs),
                         merge=True)
                for f in spec.get("merge", [])]
        return out

    @property
    def installs_skill(self) -> bool:
        return bool(self.spec.get("skill"))


TARGETS: dict[str, Target] = {
    d.name: Target(d.name, d)
    for d in sorted(ADAPTERS.iterdir() if ADAPTERS.is_dir() else [])
    if (d / "adapter.json").is_file()
}


# --------------------------------------------------------------------------- #
# install / drift
# --------------------------------------------------------------------------- #

@dataclass
class Report:
    target: str = ""
    root: Path = field(default_factory=Path)
    written: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _merge_hooks(existing: dict, payload: dict) -> bool:
    """Register the adapter's hook groups without dropping anything already there.

    Foreign events, foreign matcher groups, and every other settings key survive;
    a group is appended only when none of its commands is already registered, so
    re-installing is a no-op. Returns True if anything changed.
    """
    hooks = existing.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise HarnessError("'hooks' is not an object")
    changed = False
    for event, groups in (payload.get("hooks") or {}).items():
        current = hooks.setdefault(event, [])
        if not isinstance(current, list):
            raise HarnessError(f"hooks.{event} is not a list")
        registered = {h.get("command") for g in current if isinstance(g, dict)
                      for h in (g.get("hooks") or []) if isinstance(h, dict)}
        for group in groups:
            if any(h.get("command") in registered for h in (group.get("hooks") or [])):
                continue
            current.append(json.loads(json.dumps(group)))
            changed = True
    return changed


def _merge_missing(path: Path, payload: dict) -> list[str]:
    """Commands from `payload` that are NOT registered in the file at `path`."""
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return [f"{path.name}: unparseable JSON — left untouched; fix or delete it"]
    hooks = existing.get("hooks") if isinstance(existing, dict) else None
    out = []
    for event, groups in (payload.get("hooks") or {}).items():
        current = (hooks or {}).get(event) or []
        registered = {h.get("command") for g in current if isinstance(g, dict)
                      for h in (g.get("hooks") or []) if isinstance(h, dict)}
        for group in groups:
            for h in group.get("hooks") or []:
                if h.get("command") not in registered:
                    out.append(f"{event}: {h.get('command')} not registered")
    return out


def install(target: str, root: Path, force: bool = False) -> Report:
    if target not in TARGETS:
        raise HarnessError(f"unknown target '{target}' (have: {', '.join(sorted(TARGETS))})")
    tgt = TARGETS[target]
    root = Path(root).resolve()
    rep = Report(target=target, root=root)
    for art in tgt.artifacts():
        path = root / art.rel
        if art.merge:
            _install_merge(path, art, rep)
            continue
        if path.is_file() and not force and path.read_text(encoding="utf-8") == art.text:
            rep.kept.append(f"{art.rel} (already current)")
            continue
        if path.is_file() and not force:
            rep.kept.append(f"{art.rel} (differs — re-run with --force to regenerate)")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(art.text, encoding="utf-8")
        if art.executable:
            path.chmod(0o755)
        rep.written.append(art.rel)
    if tgt.installs_skill:
        from .agentdoc import SKILL_REL, skill_install

        stale = check_skill(root)
        skill_install(root)  # the existing machinery, reused — not duplicated
        rep.written.append(f"{SKILL_REL}/ (packaged skill)") if stale else \
            rep.kept.append(f"{SKILL_REL}/ (packaged skill already current)")
    return rep


def _install_merge(path: Path, art: Artifact, rep: Report) -> None:
    payload = json.loads(art.text)
    existing: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rep.kept.append(f"{art.rel} (unparseable JSON — left untouched, nothing merged)")
            return
        if not isinstance(loaded, dict):
            rep.kept.append(f"{art.rel} (not a JSON object — left untouched)")
            return
        existing = loaded
    try:
        changed = _merge_hooks(existing, payload)
    except HarnessError as e:
        rep.kept.append(f"{art.rel} ({e} — left untouched)")
        return
    if not changed:
        rep.kept.append(f"{art.rel} (hooks already registered)")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    rep.written.append(f"{art.rel} (merged — existing settings preserved)")


def check(target: str, root: Path) -> list[str]:
    """Drift: what an installed adapter has that the generator no longer emits.
    Empty means the installed copy is exactly what `install --force` would write."""
    if target not in TARGETS:
        raise HarnessError(f"unknown target '{target}' (have: {', '.join(sorted(TARGETS))})")
    tgt = TARGETS[target]
    root = Path(root).resolve()
    drift: list[str] = []
    for art in tgt.artifacts():
        path = root / art.rel
        if art.merge:
            drift += [f"{art.rel}: {m}" for m in _merge_missing(path, json.loads(art.text))]
            continue
        if not path.is_file():
            drift.append(f"{art.rel}: missing")
        elif path.read_text(encoding="utf-8") != art.text:
            drift.append(f"{art.rel}: differs from generated content")
    if tgt.installs_skill:
        drift += check_skill(root)
    return drift


def check_skill(root: Path) -> list[str]:
    """Drift between a project's installed skill and the packaged one — the v0.5
    test that made adapters disposable, generalized so every target can use it."""
    from .agentdoc import SKILL_DIR, SKILL_REL

    out = []
    for src in sorted(SKILL_DIR.iterdir()):
        dest = Path(root) / SKILL_REL / src.name
        if not dest.is_file():
            out.append(f"{SKILL_REL / src.name}: missing")
        elif dest.read_bytes() != src.read_bytes():
            out.append(f"{SKILL_REL / src.name}: differs from the packaged skill")
    return out


def render_report(rep: Report) -> str:
    tgt = TARGETS[rep.target]
    lines = [f"harness: {rep.target} — {tgt.description}", f"  into {rep.root}"]
    lines += [f"  + {rel}" for rel in rep.written]
    lines += [f"  · {rel}" for rel in rep.kept]
    lines += [f"  ! {note}" for note in rep.notes]
    lines.append("")
    lines.append(f"  generated from {tool()} {__version__} live tables — regenerate after upgrading;")
    lines.append(f"  `{tool()} harness check --target {rep.target}` fails if these drift.")
    return "\n".join(lines)
