"""v0.5 agent-native surface: the tool must brief, scaffold, and ship its skill
without drift. These tests are the contract that keeps the three doors open."""

import shutil
import tempfile
import unittest
from pathlib import Path

from uel.agentdoc import SKILL_DIR, briefing, init_project
from uel.diagnostics import Bag
from uel.project import load_project
from uel.resolver import resolve_project
from uel.scheduler import build

REPO = Path(__file__).resolve().parent.parent


class Briefing(unittest.TestCase):
    def test_generated_from_live_tables(self):
        text = briefing()
        from uel import __version__
        from uel.diagnostics import CODES
        from uel.expr import CONSTS, FUNCTIONS

        self.assertIn(__version__, text)
        self.assertIn(f"{len(CODES)} stable codes", text)
        for fn in FUNCTIONS:
            self.assertIn(fn, text)
        for c in CONSTS:
            self.assertIn(c.removeprefix("const."), text)
        flat = " ".join(text.lower().split())
        for needle in ("knowns are references", "subtraction needs spaces",
                       "levels add where linear quantities multiply", "uel pack",
                       "never hand-edit uel.lock"):
            self.assertIn(needle, flat)

    def test_briefing_is_context_sized(self):
        self.assertLess(len(briefing()), 6000, "the briefing must stay compact")


class InitScaffold(unittest.TestCase):
    def test_green_by_construction(self):
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        init_project(td, "widget")
        bag = Bag()
        res = resolve_project(load_project(td, bag), bag)
        self.assertTrue(bag.ok(), [d.message for d in bag.errors])
        result = build(res, bag, verbose=False)
        self.assertTrue(result.ok() and bag.ok(), [d.message for d in bag.errors])
        # the stub's declared band flows into the consumer's worst-case band
        import json

        lock = json.loads((td / "uel.lock").read_text(encoding="utf-8"))
        p_out = lock["nodes"]["OutputPower"]["outputs"]["p_out"]
        self.assertAlmostEqual(p_out["value"], 16.0, places=6)
        self.assertGreater(p_out["unc"]["value"], 1.0)
        # and the skill rides along
        self.assertTrue((td / ".claude" / "skills" / "uel-engineer" / "SKILL.md").is_file())

    def test_idempotent(self):
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        first = init_project(td, "w")
        second = init_project(td, "w")
        self.assertTrue(first)
        self.assertEqual(second, [], "init must never overwrite existing files")


class SkillShipping(unittest.TestCase):
    def test_repo_copy_matches_package(self):
        """The repo installs its own skill; CI fails if the copies drift."""
        packaged = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        installed = (REPO / ".claude" / "skills" / "uel-engineer" / "SKILL.md")
        self.assertTrue(installed.is_file(),
                        "run `uel skill install .` at the repo root and commit the result")
        self.assertEqual(installed.read_text(encoding="utf-8"), packaged,
                         "skill drift: re-run `uel skill install .` and commit")

    def test_skill_frontmatter(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: uel-engineer", text)
        self.assertIn("description:", text)


class StubUncertainty(unittest.TestCase):
    def test_stub_band_round_trips_and_evaluates(self):
        from uel.formatter import format_ast
        from uel.parser import parse_text
        from uel.uast import fingerprint

        src = ("analysis S {\n  core stub {\n    a = 10 W ± 5 %\n    b = 3 dB ± 0.5 dB\n"
               "    c = 2 K ± cal\n  }\n  outputs {\n    a : W\n    b : dB\n    c : K\n  }\n}\n")
        bag = Bag()
        ast = parse_text(src, "t.uel", bag)
        self.assertTrue(bag.ok(), [d.message for d in bag.items])
        once = format_ast(ast)
        bag2 = Bag()
        ast2 = parse_text(once, "t.uel", bag2)
        self.assertEqual(fingerprint(ast2), fingerprint(ast))
        self.assertEqual(once, format_ast(ast2), "formatter must be idempotent on stub bands")


if __name__ == "__main__":
    unittest.main()
