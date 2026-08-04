"""Phase 3 exit criterion (program §4): a change to an upstream quantity
mechanically flags every stale downstream analysis in a 50-node demo graph;
re-run restores freshness. Also: perturbations below the declared tolerance
flag nothing (spec §4.3), and the flagged set is *exact* — no over- or
under-invalidation against an independently computed reachability cone.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from uel.checker import run_checks
from uel.diagnostics import Bag
from uel.lockfile import Lock
from uel.project import load_project
from uel.resolver import resolve_project
from uel.scheduler import build
from uel.staleness import compute

STAGES = 10
WIDTH = 5  # 50 executable nodes

CORE = '''import json, sys
p = json.load(sys.stdin)
total = sum(v.get("si", v.get("value", 0.0)) for v in p["inputs"].values())
total += sum(v.get("si", v.get("value", 0.0)) for v in p["params"].values())
json.dump({"outputs": {"y": {"value": total, "unit": "m"}}}, sys.stdout)
'''


def _make_project(root: Path) -> None:
    (root / "model").mkdir(parents=True)
    (root / "cores").mkdir()
    (root / "uel.toml").write_text(
        '[project]\nname = "st50"\n\n[tolerances]\nlength = "0.001 m"\n', encoding="utf-8"
    )
    (root / "cores" / "node.py").write_text(CORE, encoding="utf-8")
    lines = ["requirement ROOT {", "  base = 100 m", "}", ""]
    for i in range(STAGES):
        for j in range(WIDTH):
            lines.append(f"analysis N_{i}_{j} {{")
            lines.append("  knowns {")
            if i == 0:
                lines.append("    base <- req.ROOT.base")
            else:
                lines.append(f"    a <- N_{i-1}_{j}.outputs.y")
                lines.append(f"    b <- N_{i-1}_{(j+1) % WIDTH}.outputs.y")
            lines.append("  }")
            lines.append(f"  params {{ bias = {i}.{j} m }}")
            lines.append('  core python "cores/node.py"')
            lines.append("  outputs { y : m }")
            lines.append("}")
            lines.append("")
    (root / "model" / "graph.uel").write_text("\n".join(lines), encoding="utf-8")


def _expected_cone(sources: set[tuple[int, int]]) -> set[str]:
    """Reachability computed independently from the known edge structure."""
    dirty = set(sources)
    for i in range(1, STAGES):
        for j in range(WIDTH):
            if (i - 1, j) in dirty or (i - 1, (j + 1) % WIDTH) in dirty:
                dirty.add((i, j))
    return {f"N_{i}_{j}" for (i, j) in dirty}


class TestStaleness50(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.root = Path(self.td)
        _make_project(self.root)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _resolve(self):
        bag = Bag()
        project = load_project(self.root, bag)
        res = resolve_project(project, bag)
        run_checks(res, bag, lock=False)
        self.assertTrue(bag.ok(), bag.render(project.sources_map()))
        return res, bag

    def _states(self, res):
        return compute(res, Lock.load(res.project.lock_path))

    def test_fifty_node_ripple(self):
        res, bag = self._resolve()
        rep = self._states(res)
        self.assertEqual(len(rep.order), STAGES * WIDTH)
        self.assertEqual(set(rep.stale()), set(rep.order), "everything starts missing")

        result = build(res, bag, verbose=False)
        self.assertTrue(result.ok(), f"failed: {result.failed}")
        self.assertEqual(len(result.ran), STAGES * WIDTH)
        self.assertEqual(self._states(res).stale(), [], "build restores freshness")

        # 1) root quantity change: every stage-0 consumer + full downstream cone
        model = self.root / "model" / "graph.uel"
        model.write_text(model.read_text().replace("base = 100 m", "base = 101 m"))
        res2, _ = self._resolve()
        stale = set(self._states(res2).stale())
        expected = _expected_cone({(0, j) for j in range(WIDTH)})
        self.assertEqual(stale, expected, "root change invalidates exactly the full cone")

        # rebuild only the stale set, everything fresh again
        bag2 = Bag()
        result2 = build(res2, bag2, verbose=False)
        self.assertTrue(result2.ok())
        self.assertEqual(len(result2.ran), len(expected))
        self.assertEqual(len(result2.skipped), STAGES * WIDTH - len(expected))
        self.assertEqual(self._states(res2).stale(), [])

        # 2) mid-graph single-node edit: exactly its cone, nothing else
        model.write_text(model.read_text().replace("params { bias = 4.2 m }",
                                                   "params { bias = 9.9 m }"))
        res3, _ = self._resolve()
        stale3 = set(self._states(res3).stale())
        expected3 = _expected_cone({(4, 2)})
        self.assertEqual(stale3, expected3, "mid-graph edit invalidates exactly its cone")

        # 3) sub-tolerance perturbation: nothing moves (tolerance grid is 1 mm)
        bag3 = Bag()
        build(res3, bag3, verbose=False)
        model.write_text(model.read_text().replace("base = 101 m", "base = 101.0004 m"))
        res4, _ = self._resolve()
        self.assertEqual(self._states(res4).stale(), [],
                         "a perturbation below the declared tolerance flags nothing")

        # 4) supra-tolerance perturbation: flags again
        model.write_text(model.read_text().replace("base = 101.0004 m", "base = 101.002 m"))
        res5, _ = self._resolve()
        self.assertEqual(set(self._states(res5).stale()),
                         _expected_cone({(0, j) for j in range(WIDTH)}))


if __name__ == "__main__":
    unittest.main()
