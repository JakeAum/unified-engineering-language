"""Core-protocol contract tests: the shell's promises are enforced, not advisory."""

import shutil
import tempfile
import unittest
from pathlib import Path

from uel.checker import run_checks
from uel.diagnostics import Bag
from uel.project import load_project
from uel.resolver import resolve_project
from uel.scheduler import build


def _proj(root: Path, model: str, cores: dict[str, str]) -> None:
    (root / "model").mkdir(parents=True)
    (root / "cores").mkdir()
    (root / "uel.toml").write_text('[project]\nname = "contract"\n', encoding="utf-8")
    (root / "model" / "m.uel").write_text(model, encoding="utf-8")
    for name, text in cores.items():
        (root / "cores" / name).write_text(text, encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.root = Path(self.td)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def run_build(self):
        bag = Bag()
        project = load_project(self.root, bag)
        res = resolve_project(project, bag)
        run_checks(res, bag, lock=False)
        self.assertTrue(bag.ok(), bag.render(project.sources_map()))
        result = build(res, bag, verbose=False)
        return result, bag

    def codes(self, bag):
        return [d.code for d in bag.items]


class TestGeometryAssertionsMandatory(Base):
    def test_no_assertions_fails(self):
        _proj(self.root, 'geometry G {\n  core python "cores/g.py"\n  outputs { mass : g }\n}\n',
              {"g.py": 'import json,sys; json.load(sys.stdin); '
                       'json.dump({"outputs":{"mass":{"value":1,"unit":"g"}}}, sys.stdout)'})
        result, bag = self.run_build()
        self.assertEqual(result.failed, ["G"])
        self.assertIn("UEL0601", self.codes(bag))

    def test_failed_assertion_fails(self):
        _proj(self.root, 'geometry G {\n  core python "cores/g.py"\n  outputs { mass : g }\n}\n',
              {"g.py": 'import json,sys; json.load(sys.stdin); '
                       'json.dump({"outputs":{"mass":{"value":1,"unit":"g"}},'
                       '"assertions":[{"name":"planar_face","passed":False if 0 else False,'
                       '"detail":"selector grabbed 3 edges, expected 4"}]}, sys.stdout)'})
        result, bag = self.run_build()
        self.assertEqual(result.failed, ["G"])
        self.assertIn("UEL0602", self.codes(bag))


class TestOutputValidation(Base):
    MODEL = 'analysis A {\n  core python "cores/a.py"\n  outputs { f : N }\n}\n'

    def test_wrong_dimension_rejected(self):
        _proj(self.root, self.MODEL,
              {"a.py": 'import json,sys; json.load(sys.stdin); '
                       'json.dump({"outputs":{"f":{"value":3,"unit":"kg"}}}, sys.stdout)'})
        result, bag = self.run_build()
        self.assertEqual(result.failed, ["A"])
        self.assertIn("UEL0704", self.codes(bag))

    def test_scale_normalized(self):
        # kN comes back, N was declared: same dimension, value normalized into N
        _proj(self.root, self.MODEL,
              {"a.py": 'import json,sys; json.load(sys.stdin); '
                       'json.dump({"outputs":{"f":{"value":1.5,"unit":"kN"}}}, sys.stdout)'})
        result, bag = self.run_build()
        self.assertTrue(result.ok())
        from uel.lockfile import Lock

        lock = Lock.load(self.root / "uel.lock")
        self.assertAlmostEqual(lock.nodes["A"].outputs["f"].value, 1500.0)
        self.assertEqual(lock.nodes["A"].outputs["f"].unit, "N")

    def test_missing_output_rejected(self):
        _proj(self.root, self.MODEL,
              {"a.py": 'import json,sys; json.load(sys.stdin); '
                       'json.dump({"outputs":{}}, sys.stdout)'})
        result, bag = self.run_build()
        self.assertEqual(result.failed, ["A"])
        self.assertIn("UEL0704", self.codes(bag))

    def test_undeclared_output_warns(self):
        _proj(self.root, self.MODEL,
              {"a.py": 'import json,sys; json.load(sys.stdin); '
                       'json.dump({"outputs":{"f":{"value":3,"unit":"N"},'
                       '"sneaky":{"value":1,"unit":"m"}}}, sys.stdout)'})
        result, bag = self.run_build()
        self.assertTrue(result.ok())
        warns = [d for d in bag.items if d.code == "UEL0704" and d.severity == "warning"]
        self.assertTrue(warns)


class TestCoreFailure(Base):
    def test_nonzero_exit_reported_with_stderr(self):
        _proj(self.root, 'analysis A {\n  core python "cores/a.py"\n  outputs { x : m }\n}\n',
              {"a.py": 'import sys; print("solver diverged: residual 8e+2", file=sys.stderr); sys.exit(3)'})
        result, bag = self.run_build()
        self.assertEqual(result.failed, ["A"])
        d = next(d for d in bag.items if d.code == "UEL0703")
        self.assertIn("solver diverged", d.reason)

    def test_failed_node_is_stale_next_time(self):
        _proj(self.root, 'analysis A {\n  core python "cores/a.py"\n  outputs { x : m }\n}\n',
              {"a.py": "import sys; sys.exit(1)"})
        self.run_build()
        from uel.lockfile import Lock
        from uel.staleness import compute

        bag = Bag()
        project = load_project(self.root, bag)
        res = resolve_project(project, bag)
        rep = compute(res, Lock.load(project.lock_path))
        self.assertEqual(rep.states["A"].status, "stale")
        self.assertIn("last run failed", rep.states["A"].reasons)


if __name__ == "__main__":
    unittest.main()
