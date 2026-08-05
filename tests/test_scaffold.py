"""ADR-0006 adoption packaging: `uel init` must produce a working project and a
harness that never breaks the repository it lands in.

The load-bearing claims, each pinned here: the scaffolded model checks clean,
builds, formats canonically (its own CI gate would pass), and produces a
non-empty agenda on day one; the compile hook blocks a broken edit with usable
diagnostics and stays silent otherwise; the settings merge preserves foreign
hooks; and every harness file degrades to a no-op when the kernel is absent.
"""

import json
import os
import shutil
import subprocess
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from uel.attention import build_agenda, info_value
from uel.checker import run_checks
from uel.cli import main as cli_main
from uel.diagnostics import Bag
from uel.formatter import format_ast
from uel.lockfile import Lock
from uel.parser import parse_text
from uel.project import load_project
from uel.resolver import resolve_project
from uel.scaffold import init
from uel.scheduler import build
from uel.staleness import compute

REPO = Path(__file__).resolve().parent.parent


def _resolve(root: Path):
    bag = Bag()
    project = load_project(root, bag)
    res = resolve_project(project, bag)
    return project, res, bag


class TestScaffoldedProject(unittest.TestCase):
    """The generated project must be real work, not a stub."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.mkdtemp()
        cls.root = Path(cls.td) / "adopter"
        cls.root.mkdir(parents=True)
        (cls.root / ".git").mkdir()  # make it look like a repo root
        cls.result = init(cls.root, name="adopter")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.td, ignore_errors=True)

    def test_wrote_project_and_harness(self):
        written = set(self.result.written)
        for expected in ("uel.toml", "model/system.uel", "analysis/frame_static.py",
                         "AGENTS.md", "CLAUDE.md", ".claude/skills/uel-loop/SKILL.md",
                         ".claude/hooks/uel-check.py", ".claude/hooks/uel-agenda.sh",
                         ".claude/settings.json", ".github/workflows/uel-gate.yml",
                         "docs/org/loop.md", "docs/org/loop-log.md"):
            self.assertIn(expected, written)
        self.assertEqual(self.result.project_rel, ".")
        for hook in (".claude/hooks/uel-check.py", ".claude/hooks/uel-agenda.sh"):
            mode = (self.root / hook).stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, f"{hook} must be executable")

    def test_checks_clean(self):
        _, res, bag = _resolve(self.root)
        run_checks(res, bag, lock=False)
        errors = [d for d in bag.items if d.severity == "error"]
        self.assertEqual(errors, [], f"starter model must check clean: {bag.to_json()}")

    def test_builds_and_agenda_is_useful_on_day_one(self):
        project, res, bag = _resolve(self.root)
        rollups = run_checks(res, bag, lock=False)
        result = build(res, bag)
        self.assertTrue(result.ok(), "starter core must run")
        self.assertEqual(len(result.failed), 0)

        project2, res2, bag2 = _resolve(self.root)
        lock = Lock.load(project2.lock_path)
        rollups = run_checks(res2, bag2, lock=False)
        agenda = build_agenda(res2, compute(res2, lock), lock, rollups, 0, 0)
        # a fresh adopter has no stale work, but the loop still has a first move:
        # the unjudged result, the ranked measurement, and a live margin
        self.assertIn("FrameStatic", agenda.pending_judgments)
        self.assertTrue(agenda.measurements)
        self.assertEqual(agenda.measurements[0].target, "req.SYS-001.rated_load")
        self.assertTrue(agenda.budgets)

    def test_formatter_canonical(self):
        """The generated CI runs `uel fmt --check`; the scaffold must survive it."""
        for rel in ("model/requirements.uel", "model/system.uel"):
            src = (self.root / rel).read_text(encoding="utf-8")
            bag = Bag()
            ast = parse_text(src, rel, bag)
            self.assertFalse(bag.errors, f"{rel} must parse")
            self.assertEqual(format_ast(ast), src, f"{rel} is not formatter-canonical")

    def test_info_value_ranks_the_calibration_pending_load(self):
        project, res, _ = _resolve(self.root)
        lock = Lock.load(project.lock_path)
        mv = info_value(res, compute(res, lock), lock)
        self.assertEqual(mv[0].target, "req.SYS-001.rated_load")
        self.assertEqual(mv[0].ignorance, 1.0)  # ± cal
        self.assertGreater(mv[0].fence_pressure, 0.0)

    def test_campaign_template_is_valid_and_targets_a_real_quantity(self):
        payload = json.loads((self.root / "test" / "example-campaign.json").read_text())
        _, res, _ = _resolve(self.root)
        for m in payload["measurements"]:
            node, _, member = m["target"].rpartition(".")
            self.assertIn(node, res.doc.nodes, "campaign target must name a real node")


class TestHarnessSafety(unittest.TestCase):
    """A scaffolded repo must never be broken by its own tooling."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.root = Path(self.td) / "repo"
        self.root.mkdir(parents=True)
        (self.root / ".git").mkdir()
        init(self.root, name="repo")
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)

    def _run_hook(self, payload: dict, importable: bool) -> subprocess.CompletedProcess:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root))
        # the hook shells out to `uel`/`python -m uel`; make the kernel
        # importable (or not) exactly as an adopter's machine would
        env["PYTHONPATH"] = str(REPO) if importable else ""
        env["PATH"] = "/usr/bin:/bin"  # no installed `uel` entry point
        return subprocess.run(
            [sys.executable, str(self.root / ".claude" / "hooks" / "uel-check.py")],
            input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=180,
            # run from the adopter's repo, as a real session does — otherwise the
            # UEL checkout leaks onto sys.path via cwd and nothing is proven
            cwd=str(self.root),
        )

    def test_hook_blocks_broken_edit_with_usable_diagnostics(self):
        model = self.root / "model" / "system.uel"
        model.write_text(model.read_text().replace("load in [0, 1000 N]", "load in [0, 500 N]"))
        r = self._run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(model)}}, importable=True)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("UEL0501", r.stderr)  # the code
        self.assertIn("fence", r.stderr)  # the reason, not just a failure

    def test_hook_silent_on_clean_edit(self):
        model = self.root / "model" / "system.uel"
        r = self._run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(model)}}, importable=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr.strip(), "")

    def test_hook_ignores_non_model_edits_and_foreign_files(self):
        for path in (self.root / "README.md", Path("/tmp") / "elsewhere.uel"):
            r = self._run_hook(
                {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}, importable=True)
            self.assertEqual(r.returncode, 0, f"{path} must not trigger the gate")

    def test_hook_is_a_noop_without_the_kernel(self):
        """An adopter who has not installed UEL yet must not be blocked."""
        model = self.root / "model" / "system.uel"
        model.write_text(model.read_text().replace("load in [0, 1000 N]", "load in [0, 500 N]"))
        r = self._run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(model)}}, importable=False)
        self.assertEqual(r.returncode, 0)

    def test_hook_survives_garbage_input(self):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root), PYTHONPATH=str(REPO))
        r = subprocess.run(
            [sys.executable, str(self.root / ".claude" / "hooks" / "uel-check.py")],
            input="not json at all", capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0)


class TestSettingsMerge(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.root = Path(self.td) / "repo"
        (self.root / ".claude").mkdir(parents=True)
        (self.root / ".git").mkdir()
        self.settings = self.root / ".claude" / "settings.json"
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)

    def test_preserves_foreign_settings_and_hooks(self):
        self.settings.write_text(json.dumps({
            "permissions": {"allow": ["Bash(npm test:*)"]},
            "hooks": {"PostToolUse": [
                {"matcher": "Write", "hooks": [{"type": "command", "command": "./fmt.sh"}]}]},
        }), encoding="utf-8")
        init(self.root, name="repo")
        merged = json.loads(self.settings.read_text())
        self.assertEqual(merged["permissions"]["allow"], ["Bash(npm test:*)"])
        commands = [h["command"] for g in merged["hooks"]["PostToolUse"] for h in g["hooks"]]
        self.assertIn("./fmt.sh", commands)
        self.assertIn("$CLAUDE_PROJECT_DIR/.claude/hooks/uel-check.py", commands)
        self.assertIn("SessionStart", merged["hooks"])

    def test_rerun_is_idempotent(self):
        init(self.root, name="repo")
        first = self.settings.read_text()
        second_result = init(self.root, name="repo")
        self.assertEqual(self.settings.read_text(), first)
        self.assertEqual(second_result.written, [])  # everything already present
        self.assertTrue(any("already registered" in s for s in second_result.skipped))

    def test_unparseable_settings_left_untouched(self):
        self.settings.write_text("{ not json", encoding="utf-8")
        result = init(self.root, name="repo")
        self.assertEqual(self.settings.read_text(), "{ not json")
        self.assertTrue(any("unparseable" in s for s in result.skipped))


class TestInitCli(unittest.TestCase):
    def test_init_into_subdirectory_wires_paths_everywhere(self):
        td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        root = Path(td) / "repo"
        (root / ".git").mkdir(parents=True)
        rc = cli_main(["init", str(root / "hardware"), "--name", "sub"])
        self.assertEqual(rc, 0)
        self.assertTrue((root / "hardware" / "uel.toml").is_file())
        self.assertIn("PROJECT_REL = \"hardware\"",
                      (root / ".claude" / "hooks" / "uel-check.py").read_text())
        self.assertIn("uel check hardware",
                      (root / ".github" / "workflows" / "uel-gate.yml").read_text())
        self.assertIn("hardware", (root / "AGENTS.md").read_text())

    def test_harness_none_writes_project_only(self):
        td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        root = Path(td) / "repo"
        (root / ".git").mkdir(parents=True)
        result = init(root, name="bare", harness="none")
        self.assertTrue((root / "uel.toml").is_file())
        self.assertFalse((root / ".claude").exists())
        self.assertFalse(any(w.startswith("AGENTS") for w in result.written))

    def test_existing_files_are_kept_unless_forced(self):
        td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        root = Path(td) / "repo"
        (root / ".git").mkdir(parents=True)
        (root / "AGENTS.md").write_text("mine, do not clobber", encoding="utf-8")
        init(root, name="repo")
        self.assertEqual((root / "AGENTS.md").read_text(), "mine, do not clobber")
        init(root, name="repo", force=True)
        self.assertIn("agent boot context", (root / "AGENTS.md").read_text())


if __name__ == "__main__":
    unittest.main()
