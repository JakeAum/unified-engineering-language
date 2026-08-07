"""The agent-facing surface (v0.5): UEL describes itself to the model using it.

Four doors now, one source of truth — `uel harness` (ADR-0010) generates a
specific harness's hooks and boot context from the same live tables:
- `uel agent`  — a compact briefing generated from the LIVE kernel tables
  (error codes, expression functions/constants, level units, CLI commands), so
  it cannot drift from the implementation;
- `uel skill install [dir]` — copies the packaged agent skill into a project's
  `.claude/skills/`, for harnesses that load skills;
- `uel init <dir>` — a green-by-construction starter project that teaches the
  loop by existing.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import __version__, EDITION
from .diagnostics import CODES

SKILL_DIR = Path(__file__).resolve().parent / "skill"
SKILL_NAME = "uel-engineer"
# Where an installed copy lands in a project. A live table: the harness adapters
# quote this path rather than retyping it (uel/harness.py).
SKILL_REL = Path(".claude") / "skills" / SKILL_NAME

FAMILIES: tuple[tuple[str, str], ...] = (
    ("UEL00xx", "project / io / lock"),
    ("UEL01xx", "lexing and parsing"),
    ("UEL02xx", "names and references"),
    ("UEL03xx", "units, dimensions, levels, expressions"),
    ("UEL04xx", "conservation: connections, nets, budgets"),
    ("UEL05xx", "envelopes: fences, structural claims, model hazards"),
    ("UEL06xx", "geometry assertions and DFM"),
    ("UEL07xx", "staleness, build, core execution"),
    ("UEL08xx", "calibration, targets, seams, verification"),
    ("UEL10xx", "doctor: drift and epistemic debt over the lock"),
)


def briefing(commands: list[str] | None = None) -> str:
    from .expr import CONSTS, FUNCTIONS
    from .units import UNITS

    levels = sorted(n for n, u in UNITS.items() if u.level)
    lines = [
        f"UEL {__version__} (edition {EDITION}) — agent briefing. The tool is the source of",
        "truth for this text; docs/ carries the depth, `.claude/skills/uel-engineer/`",
        "(or `uel skill install`) carries the operating skill.",
        "",
        "WHAT THIS IS — a content-addressed, typed graph of engineering claims:",
        "components exchange conserved quantities across ports; analyses argue claims",
        "with declared framings, referenced knowns, executable cores, and judgments;",
        "envelopes fence validity; hashes make change computable and exact.",
        "",
        "THE LOOP — edit .uel sources; `uel check` (read every diagnostic: stable code",
        "+ reason + often a verbatim fix); `uel build` (runs exactly the stale cone,",
        "re-verdicts targets/seams/contracts); write judgment WITH doubts; `uel fmt`;",
        "commit sources + uel.lock. Never hand-edit uel.lock or out/.",
        "",
        "SYNTAX IN SIX LINES:",
        "  requirement LNK-002 { eirp_dbw = 22 dBW ± cal  min_margin_db = 3 dB }",
        "  analysis LinkMargin {",
        "    knowns { eirp_dbw <- req.LNK-002.eirp_dbw  gt <- Gt.outputs.g_over_t_dbk }",
        "    core expr { margin_db = eirp_dbw - (235.3 dB) + gt - db(const.k_B) - (4 dB) }",
        "    outputs { margin_db : dB ± target >= req.LNK-002.min_margin_db }",
        "    judgment accepted \"closes\" doubts \"EIRP is ± cal and moves margin 1:1\" }",
        "",
        "HARD RULES — knowns are references, never copies (analysis outputs need the",
        "`.outputs.` segment). Every value carries a unit; ± abs/rel/cal uncertainty;",
        "`from \"...\"` provenance tails. In expressions: subtraction needs spaces",
        "(identifiers may contain hyphens); units bind greedily after literals — write",
        "`(3 m) / span` when dividing by a name; outputs assigned once, in order;",
        "`let` names intermediates; no conditionals (that is a python core's job).",
        "",
        "LEVELS — dB units carry their reference in the type: "
        + " ".join(levels) + ", plus",
        "composition (dB/K, dBW/(K*Hz)). One rule: levels add where linear quantities",
        "multiply. db(x) lifts linear->level, lin(x) drops back; a bare scalar",
        "multiplies only plain dB; level uncertainty is a dB delta (± 1.5 dB).",
        "",
        "EXPRESSION CORES — functions: " + " ".join(FUNCTIONS) + ".",
        "Constants: " + " ".join(sorted(CONSTS)) + ".",
        "Types (dimension + level) are inferred through the whole body before any run;",
        "evaluation is interval arithmetic over the knowns' declared bands (worst-case",
        "enclosure). `core stub { x = 4 dB }` declares a ledgered placeholder.",
        "",
        "VERIFICATION (make opaque cores answer for themselves):",
        "  core python \"p.py\" { tool \"su2\" \"8.0.1\"  interface \"m.xml\" sha256 \"…\" }",
        "  verify out against Oracle.outputs.out within 10 %   (lock-vs-lock cross-check)",
        "  verify out monotone with input rising               (build-time perturbation)",
        "  verify case \"golden.json\" within 1 %                (re-proven every build)",
        "  verify converged residual <= 1e-6   (core must report it in 'convergence';",
        "                                       silence is a failed run, not a clean one)",
        "A run that breaks its own contract is a failed run. Targets on outputs make",
        "acceptance a computed verdict, not prose.",
        "",
        "HAZARDS — the devil is in the details at every layer. A registered model",
        "(stdlib/models.uel) names the failure modes it is structurally BLIND to",
        "(euler_bernoulli cannot see lateral-torsional buckling; a load ledger cannot",
        "see inrush). Using one obliges you per hazard (UEL0510): an analysis with",
        "`covers <hazard>` in its framing, or `waive <hazard> because \"reason\"` —",
        "a waiver without a reason is denial. `uel query sensitivity <node>` shows",
        "elasticities (superlinear ▲ = errors amplify: the t^3 flange, the V^2 gust);",
        "run it before trusting any margin. Status carries the coverage ledger.",
        "",
        f"DIAGNOSTICS — {len(CODES)} stable codes:",
    ]
    lines += [f"  {fam}  {desc}" for fam, desc in FAMILIES]
    cmds = commands or ["check", "fmt", "build", "stale", "hash", "project", "pack",
                        "graph", "calibrate", "query", "agent", "init", "skill"]
    lines += [
        "",
        "CLI — uel " + " | ".join(cmds) + ".",
        "Start anywhere with: uel check <dir>; uel project status <dir> (verdicts +",
        "trust ledger); uel pack <Analysis> <dir> (one node's full epistemic chain for",
        "review); uel query provenance <ref> <dir>; uel calibrate <measurements.json>",
        "<dir> (reality writes back; consumers flip stale mechanically).",
        "",
        "DEEP DOCS — docs/syntax.md · docs/schema.md · docs/core-protocol.md ·",
        "docs/decisions/ (ADRs: why it is this way) · examples/ground-station* (a full",
        "multi-agent design, locks included).",
    ]
    return "\n".join(lines) + "\n"


def skill_install(project_dir: Path) -> Path:
    """Copy the packaged skill into <project>/.claude/skills/uel-engineer/."""
    dest = project_dir / SKILL_REL
    dest.mkdir(parents=True, exist_ok=True)
    for src in SKILL_DIR.iterdir():
        shutil.copy2(src, dest / src.name)
    return dest


_TOML = """\
[project]
name = "{name}"
edition = "2026"
model = ["model"]

[tolerances]
mass = "0.1 g"
length = "0.01 mm"
force = "0.1 N"
power = "0.01 W"
temperature = "0.001 K"
ratio_level = "0.001 dB"
default_rel = 1e-6
"""

_REQS = """\
# Requirements are the anchors analyses point their intent at. Values here are
# load-bearing references: a change ripples through every consumer mechanically.
requirement REQ-001 {
  text "The widget shall deliver at least the required output power from the available supply."
  supply_power = 20 W ± 5 %
  min_output = 12 W
}
"""

_DESIGN = """\
# A green-by-construction starter: one ledgered stub (replace with a python
# core or measured data) and one expr analysis whose acceptance is a computed
# target. Run `uel check .` then `uel build .`; see `uel agent` for the loop.
analysis Efficiency {
  doc "placeholder until a converter is chosen — publicly ledgered as a stub"
  core stub {
    eta = 0.8 ± 5 %
  }
  outputs {
    eta : dimensionless
  }
  judgment pending
}

analysis OutputPower {
  intent req.REQ-001 "does the widget meet its output power floor?"
  framing {
    model power.efficiency_chain
    assume steady_state because "worst-case continuous draw; no transients modeled"
  }
  knowns {
    supply <- req.REQ-001.supply_power
    eta <- Efficiency.outputs.eta
  }
  core expr {
    p_out = supply * eta
  }
  outputs {
    p_out : W ± target >= req.REQ-001.min_output
  }
  judgment pending
}
"""

_AGENTS_MD = """\
# Agent notes

This is a UEL project. Orient with `uel agent`; the operating skill is in
`.claude/skills/uel-engineer/` (or `uel skill install .`).

The loop: edit `model/*.uel` -> `uel check .` -> fix every diagnostic ->
`uel build .` -> write judgments with doubts -> `uel fmt .` -> commit sources
AND `uel.lock`. Never hand-edit `uel.lock` or `out/`.
"""


def init_project(root: Path, name: str) -> list[Path]:
    """Scaffold a minimal project that checks and builds green immediately."""
    (root / "model").mkdir(parents=True, exist_ok=True)
    files = {
        root / "uel.toml": _TOML.format(name=name),
        root / "model" / "requirements.uel": _REQS,
        root / "model" / "design.uel": _DESIGN,
        root / "AGENTS.md": _AGENTS_MD,
    }
    written = []
    for p, text in files.items():
        if not p.exists():
            p.write_text(text, encoding="utf-8")
            written.append(p)
    skill_install(root)
    return written
