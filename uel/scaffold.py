"""`uel init` — scaffold a UEL project, and the agent harness around it.

Adoption is a feature of the language, not a README exercise (ADR-0006). A
kernel nobody can start using in one command is a kernel that stays in one
repository, and the leverage claim is only falsifiable once someone *outside*
this program tries it.

`uel init` writes two layers into a repository:

**The project** (at the target path) — manifest with hash tolerances, a starter
model that checks clean and builds, a core following the JSON protocol, a
measurement-campaign template, and the calibration directories reality writes
back into.

**The harness** (at the repo root) — the affordances an agent org needs to work
that project without shared context:

| file | what it does |
|---|---|
| `AGENTS.md` + `CLAUDE.md` | boot context: what the graph guarantees, and what it never will |
| `.claude/skills/uel-loop/SKILL.md` | the iteration protocol, invocable by name |
| `.claude/skills/uel-doctor/SKILL.md` | the checkup, and how to file a kernel defect upstream without leaking the model |
| `.claude/hooks/uel-check.py` | PostToolUse: compile gate on every `.uel` edit, diagnostics fed back |
| `.claude/hooks/uel-agenda.sh` | SessionStart: a waking agent boots with the work queue |
| `.claude/settings.json` | hook registration (merged, never clobbered) |
| `.github/workflows/uel-gate.yml` | the merge gate: check, fmt, build, lock-is-current |
| `docs/org/loop.md`, `loop-log.md` | the standing protocol and its cost denominator |

Nothing here is Claude-specific except the `.claude/` directory: `AGENTS.md` is
the vendor-neutral boot document and every harness file degrades to a silent
no-op when the kernel is absent. `--harness none` writes the project alone.

Templates are package data (`uel/templates/`), rendered by `{{TOKEN}}`
substitution — not `str.format`, because the templates are full of literal
braces (JSON, Python, UEL blocks).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"

# (template, destination relative to its layer root, executable?)
PROJECT_FILES: list[tuple[str, str, bool]] = [
    ("uel.toml.tmpl", "uel.toml", False),
    ("model_requirements.uel.tmpl", "model/requirements.uel", False),
    ("model_system.uel.tmpl", "model/system.uel", False),
    ("analysis_frame_static.py.tmpl", "analysis/frame_static.py", False),
    ("test_campaign.json.tmpl", "test/example-campaign.json", False),
]

HARNESS_FILES: list[tuple[str, str, bool]] = [
    ("AGENTS.md.tmpl", "AGENTS.md", False),
    ("CLAUDE.md.tmpl", "CLAUDE.md", False),
    ("skill.md.tmpl", ".claude/skills/uel-loop/SKILL.md", False),
    ("skill_doctor.md.tmpl", ".claude/skills/uel-doctor/SKILL.md", False),
    ("hook_check.py.tmpl", ".claude/hooks/uel-check.py", True),
    ("hook_agenda.sh.tmpl", ".claude/hooks/uel-agenda.sh", True),
    ("workflow.yml.tmpl", ".github/workflows/uel-gate.yml", False),
    ("loop.md.tmpl", "docs/org/loop.md", False),
    ("loop-log.md.tmpl", "docs/org/loop-log.md", False),
]

# Directories the loop writes into; created empty so the layout is legible and
# `git add` finds them before the first measurement lands.
PROJECT_DIRS = ["calibration", "out"]

HOOK_SETTINGS = {
    "hooks": {
        "SessionStart": [
            {"hooks": [{"type": "command",
                        "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/uel-agenda.sh"}]}
        ],
        "PostToolUse": [
            {"matcher": "Edit|Write|MultiEdit|NotebookEdit",
             "hooks": [{"type": "command",
                        "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/uel-check.py"}]}
        ],
    }
}


@dataclass
class InitResult:
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    project_rel: str = "."
    repo_root: Path = field(default_factory=Path)

    def ok(self) -> bool:
        return bool(self.written)


def find_repo_root(start: Path) -> Path:
    """Nearest ancestor holding .git; the project dir itself if there is none.
    The harness belongs at the repo root even when the model lives deeper."""
    start = start.resolve()
    for cand in (start, *start.parents):
        if (cand / ".git").exists():
            return cand
    return start


def render(template: str, params: dict[str, str]) -> str:
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    for key, value in params.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _write(path: Path, text: str, executable: bool, force: bool,
           result: InitResult, root: Path) -> None:
    rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    if path.exists() and not force:
        result.skipped.append(rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)
    result.written.append(rel)


def merge_settings(path: Path, result: InitResult, root: Path) -> None:
    """Register the hooks without clobbering settings the repo already has.

    Existing events and matcher groups are preserved; our commands are appended
    only where an identical command is not already registered, so re-running
    `uel init` is safe and someone else's hooks are never dropped.
    """
    rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    existing: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            result.skipped.append(f"{rel} (unparseable; left untouched)")
            return

    hooks = existing.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        result.skipped.append(f"{rel} ('hooks' is not an object; left untouched)")
        return

    changed = False
    for event, groups in HOOK_SETTINGS["hooks"].items():
        current = hooks.setdefault(event, [])
        if not isinstance(current, list):
            continue
        registered = {
            h.get("command")
            for g in current if isinstance(g, dict)
            for h in (g.get("hooks") or []) if isinstance(h, dict)
        }
        for group in groups:
            if any(h["command"] in registered for h in group["hooks"]):
                continue
            current.append(json.loads(json.dumps(group)))  # deep copy of the literal
            changed = True

    if not changed:
        result.skipped.append(f"{rel} (hooks already registered)")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    result.written.append(rel)


def init(path: str | Path, name: str = "", harness: str = "claude",
         force: bool = False) -> InitResult:
    project = Path(path).resolve()
    repo_root = find_repo_root(project)
    project_rel = str(project.relative_to(repo_root)) if project.is_relative_to(repo_root) else "."
    if project_rel == ".":
        project_rel = "."
    result = InitResult(project_rel=project_rel, repo_root=repo_root)

    params = {
        "NAME": name or project.name or "uel-project",
        "PROJECT_REL": project_rel,
        "BRANCH_PREFIX": "model/",
    }

    for template, dest, executable in PROJECT_FILES:
        _write(project / dest, render(template, params), executable, force, result, repo_root)
    for d in PROJECT_DIRS:
        (project / d).mkdir(parents=True, exist_ok=True)
        keep = project / d / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")

    if harness == "claude":
        for template, dest, executable in HARNESS_FILES:
            _write(repo_root / dest, render(template, params), executable, force, result, repo_root)
        merge_settings(repo_root / ".claude" / "settings.json", result, repo_root)

    return result


def render_result(result: InitResult, harness: str) -> str:
    L = [f"init: wrote {len(result.written)} file(s) under {result.repo_root}"]
    for rel in result.written:
        L.append(f"  + {rel}")
    for rel in result.skipped:
        L.append(f"  · {rel} (exists — kept; re-run with --force to overwrite)")
    p = result.project_rel
    L.append("")
    L.append("next:")
    L.append(f"  uel check {p}     # the starter model checks clean")
    L.append(f"  uel build {p}     # run its core; then write the judgment")
    L.append(f"  uel agenda {p}    # what matters most, from here on")
    if harness == "claude":
        L.append("")
        L.append("the harness is live for agent sessions in this repo: the agenda prints at")
        L.append("session start, `uel check` runs on every .uel edit, and the `uel-loop` skill")
        L.append("carries the iteration protocol. Model, don't describe — load-bearing or dead.")
    return "\n".join(L)
