"""ADR-0005 attention machinery: the economics scheduler.

Pins: the band-pressure primitive (including the exact-zero-lower-bound rule
and affine SI behavior), failed-last-run outranking everything, info-value
ordering (declared ignorance × consumer cone × fence pressure, exact values
and unconsumed library values dropped), candidate-entailment-rule emission on
output discrepancies, and agenda determinism.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from uel.attention import band_pressure, build_agenda, info_value, rank
from uel.checker import run_checks
from uel.diagnostics import Bag
from uel.lockfile import Lock
from uel.project import load_project
from uel.resolver import resolve_project
from uel.scheduler import build
from uel.staleness import compute

GOOD_CORE = """import json, sys
json.load(sys.stdin)
json.dump({"outputs": {"y": {"value": 40.0, "unit": "degC"}}}, sys.stdout)
"""

BAD_CORE = """import sys
sys.exit(3)
"""

MODEL = """
requirement LOAD {
  limit = 950 N ± cal
}

requirement TEMP {
  max = 60 degC ± 5 degC
}

analysis Hot {
  intent req.LOAD "carry the limit load"
  framing {
    envelope { limit in [0, 1000 N] }
    assume steady_state because "test fixture"
  }
  knowns { limit <- req.LOAD.limit }
  core python "cores/good.py"
  outputs { y : degC }
}

analysis Mid {
  knowns { a <- Hot.outputs.y }
  core python "cores/good.py"
  outputs { y : degC }
}

analysis Broken {
  knowns { t <- req.TEMP.max }
  core python "cores/bad.py"
  outputs { y : degC }
}
"""


def _make_project(root: Path, model: str = MODEL) -> None:
    (root / "model").mkdir(parents=True)
    (root / "cores").mkdir()
    (root / "uel.toml").write_text('[project]\nname = "attn"\n', encoding="utf-8")
    (root / "cores" / "good.py").write_text(GOOD_CORE, encoding="utf-8")
    (root / "cores" / "bad.py").write_text(BAD_CORE, encoding="utf-8")
    (root / "model" / "m.uel").write_text(model, encoding="utf-8")


def _load(root: Path):
    bag = Bag()
    project = load_project(root, bag)
    res = resolve_project(project, bag)
    assert not bag.errors, bag.to_json()
    return project, res, bag


class TestBandPressure(unittest.TestCase):
    def test_crossing_is_max_pressure(self):
        p, note = band_pressure((900.0, 1100.0), 0.0, 1000.0)
        self.assertEqual(p, 1.0)
        self.assertIn("above", note)
        p, note = band_pressure((-5.0, 10.0), 0.0, 1000.0)
        self.assertEqual(p, 1.0)
        self.assertIn("below", note)

    def test_zero_lower_bound_is_one_sided(self):
        # a tiny load against [0, 260] is the safest case, not the hottest
        p, _ = band_pressure((10.0, 10.0), 0.0, 260.0)
        self.assertAlmostEqual(p, 10.0 / 260.0, places=9)
        p, _ = band_pressure((245.0, 245.0), 0.0, 260.0)
        self.assertAlmostEqual(p, 1.0 - 15.0 / 260.0, places=9)

    def test_two_sided_uses_nearest_edge(self):
        # 60 degC in [0, 100] degC arrives in SI, so the fence is genuinely
        # two-sided (273.15 K is not zero) and the nearest edge governs
        p, _ = band_pressure((333.15, 333.15), 273.15, 373.15)
        self.assertAlmostEqual(p, 0.6, places=9)

    def test_no_fence_no_pressure(self):
        self.assertEqual(band_pressure((1.0, 2.0), None, None), (0.0, ""))


class TestRank(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.root = Path(self.td)
        _make_project(self.root)
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)

    def test_missing_graph_ranks_hot_first(self):
        project, res, _ = _load(self.root)
        lock = Lock.load(project.lock_path)
        ranked = rank(res, compute(res, lock), lock)
        self.assertEqual([r.name for r in ranked][:2], ["Hot", "Broken"])
        hot = ranked[0]
        self.assertTrue(hot.frontier)
        self.assertEqual(hot.serves, "req.LOAD")
        self.assertEqual(hot.blocked_downstream, 1)
        self.assertAlmostEqual(hot.fence_pressure, 0.95, places=6)
        mid = next(r for r in ranked if r.name == "Mid")
        self.assertFalse(mid.frontier)

    def test_failed_last_run_outranks_everything(self):
        project, res, bag = _load(self.root)
        run_checks(res, bag, lock=False)
        build(res, bag)  # Broken's core exits 3; lock records the failure
        bag2 = Bag()
        project2 = load_project(self.root, bag2)
        res2 = resolve_project(project2, bag2)
        lock = Lock.load(project2.lock_path)
        ranked = rank(res2, compute(res2, lock), lock)
        self.assertTrue(ranked, "a failed node must stay ranked")
        self.assertEqual(ranked[0].name, "Broken")
        self.assertTrue(ranked[0].failed_last_run)
        self.assertGreaterEqual(ranked[0].score, 8.0)


class TestInfoValue(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.root = Path(self.td)
        _make_project(self.root)
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)

    def test_ordering_and_composition(self):
        project, res, _ = _load(self.root)
        lock = Lock.load(project.lock_path)
        mv = info_value(res, compute(res, lock), lock)
        by_target = {m.target: m for m in mv}
        # calibration-pending, 2-analysis cone, 95 % fence: the clear top
        self.assertEqual(mv[0].target, "req.LOAD.limit")
        top = mv[0]
        self.assertEqual(top.ignorance, 1.0)
        self.assertEqual(top.consumers, 2)  # Hot + Mid
        self.assertAlmostEqual(top.fence_pressure, 0.95, places=6)
        self.assertAlmostEqual(top.value, 1.0 * 3 * 1.95, places=6)
        # ± 5 degC about 60: ignorance 10/60, one consumer, no fence
        t = by_target["req.TEMP.max"]
        self.assertAlmostEqual(t.ignorance, 10.0 / 60.0, places=6)
        self.assertEqual(t.consumers, 1)

    def test_exact_values_carry_no_ignorance(self):
        model = MODEL.replace("limit = 950 N ± cal", "limit = 950 N") \
                     .replace("max = 60 degC ± 5 degC", "max = 60 degC")
        shutil.rmtree(self.root)
        _make_project(self.root, model)
        project, res, _ = _load(self.root)
        lock = Lock.load(project.lock_path)
        targets = {m.target for m in info_value(res, compute(res, lock), lock)}
        self.assertNotIn("req.LOAD.limit", targets)
        self.assertNotIn("req.TEMP.max", targets)

    def test_locked_outputs_become_validation_targets(self):
        project, res, bag = _load(self.root)
        run_checks(res, bag, lock=False)
        build(res, bag, only=["Hot"])
        bag2 = Bag()
        project2 = load_project(self.root, bag2)
        res2 = resolve_project(project2, bag2)
        lock = Lock.load(project2.lock_path)
        mv = info_value(res2, compute(res2, lock), lock)
        kinds = {m.target: m.kind for m in mv}
        # Hot ran and its prediction exists, but the core declared it exact —
        # validation targets appear only where the model declared uncertainty
        self.assertNotIn("Hot.outputs.y", kinds)


class TestCandidateRules(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.root = Path(self.td)
        _make_project(self.root)
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)

    def test_output_discrepancy_emits_reviewable_candidate(self):
        from uel.calibration import ingest

        project, res, bag = _load(self.root)
        run_checks(res, bag, lock=False)
        build(res, bag, only=["Hot"])
        bag2 = Bag()
        project2 = load_project(self.root, bag2)
        res2 = resolve_project(project2, bag2)
        payload = {
            "source": "seeded bench test", "ts": "2026-08-05T00:00:00Z",
            "measurements": [
                {"target": "Hot.outputs.y", "value": 95.0, "unit": "degC"},
            ],
        }
        summary = ingest(res2, bag2, payload)
        self.assertEqual(summary["discrepancies"], 1)
        self.assertEqual(summary["candidate_rules"], 1)
        rules = list((self.root / "calibration" / "candidate-rules").glob("*.md"))
        self.assertEqual(len(rules), 1)
        text = rules[0].read_text(encoding="utf-8")
        self.assertIn("steady_state", text)  # the declared claim is the suspect
        self.assertIn("merge gate", text)  # reviewable, never automatic

    def test_agenda_surfaces_epistemic_debt(self):
        self.test_output_discrepancy_emits_reviewable_candidate()
        bag = Bag()
        project = load_project(self.root, bag)
        res = resolve_project(project, bag)
        rollups = run_checks(res, bag, lock=False)
        lock = Lock.load(project.lock_path)
        rep = compute(res, lock)
        a = build_agenda(res, rep, lock, rollups, 0, 0)
        self.assertEqual(len(a.discrepancies), 1)
        self.assertEqual(a.discrepancies[0]["target"], "Hot.outputs.y")
        self.assertEqual(len(a.candidate_rules), 1)
        self.assertEqual(len(a.stubs), 1)
        self.assertIn("Hot", a.pending_judgments)
        # determinism: two builds of the agenda are byte-identical
        b = build_agenda(res, rep, lock, rollups, 0, 0)
        self.assertEqual(json.dumps(a.to_obj(), sort_keys=True),
                         json.dumps(b.to_obj(), sort_keys=True))


if __name__ == "__main__":
    unittest.main()
