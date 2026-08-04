"""Calibration loop tests (spec §8): tightening, discrepancy, as-built overlays,
and the staleness consequence of a measurement replacing a consumed value."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from uel.calibration import apply_overlays, ingest, load_overlay
from uel.checker import run_checks
from uel.diagnostics import Bag
from uel.lockfile import Lock
from uel.project import load_project
from uel.resolver import resolve_project
from uel.scheduler import build
from uel.staleness import compute

MODEL = """
requirement STR-1 {
  text "hold the line"
  limit_load = 10 kN
}

component Fitting : physical {
  stiffness = 42 kN/mm ± 20 %
  mass = 120 g ± 5 g
}

analysis FitDeflection {
  intent req.STR-1
  knowns {
    load <- req.STR-1.limit_load
    k <- Fitting.stiffness
  }
  core python "cores/defl.py"
  outputs { w : mm ± }
}
"""

CORE = """import json, sys
p = json.load(sys.stdin)
load = p["inputs"]["load"]["si"]
k = p["inputs"]["k"]["si"]
json.dump({"outputs": {"w": {"value": load / k * 1000, "unit": "mm",
                              "unc": {"kind": "rel", "value": 0.1}}}}, sys.stdout)
"""


class TestCalibration(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.root = Path(self.td)
        (self.root / "model").mkdir()
        (self.root / "cores").mkdir()
        (self.root / "uel.toml").write_text('[project]\nname = "cal"\n')
        (self.root / "model" / "m.uel").write_text(MODEL)
        (self.root / "cores" / "defl.py").write_text(CORE)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _res(self, serial=""):
        bag = Bag()
        project = load_project(self.root, bag)
        res = resolve_project(project, bag)
        apply_overlays(res, serial)
        run_checks(res, bag, lock=False)
        self.assertTrue(bag.ok(), bag.render(project.sources_map()))
        return res, bag

    def _ingest(self, measurements, serial=""):
        res, _ = self._res()
        bag = Bag()
        payload = {"source": "test rig", "ts": "2026-08-04T00:00:00Z",
                   **({"serial": serial} if serial else {}),
                   "measurements": measurements}
        summary = ingest(res, bag, payload, write_stubs=True)
        return summary, bag

    def test_tightening_recorded(self):
        summary, bag = self._ingest(
            [{"target": "Fitting.stiffness", "value": 44.1, "unit": "kN/mm",
              "unc": {"kind": "rel", "value": 0.03}}]
        )
        self.assertEqual(summary["tightened"], 1)
        self.assertEqual(summary["discrepancies"], 0)
        self.assertTrue(any(d.code == "UEL0803" for d in bag.items))
        hist = load_overlay(self.root)["Fitting.stiffness"]
        self.assertEqual(hist[-1]["verdict"], "tightening")

    def test_measurement_invalidates_consumers(self):
        res, bag = self._res()
        self.assertTrue(build(res, bag, verbose=False).ok())
        self._ingest([{"target": "Fitting.stiffness", "value": 44.1, "unit": "kN/mm",
                       "unc": {"kind": "rel", "value": 0.03}}])
        res2, _ = self._res()
        rep = compute(res2, Lock.load(res2.project.lock_path))
        self.assertEqual(rep.states["FitDeflection"].status, "stale")
        self.assertTrue(any("input 'k' changed" in r for r in rep.states["FitDeflection"].reasons))
        # measured provenance visible on the applied quantity
        fitting = res2.doc.components()["Fitting"]
        self.assertEqual(fitting.quantities["stiffness"].prov.kind, "measured")

    def test_discrepancy_opens_investigation(self):
        summary, bag = self._ingest(
            [{"target": "Fitting.mass", "value": 160.0, "unit": "g",
              "unc": {"kind": "abs", "value": 1.0}}]
        )
        self.assertEqual(summary["discrepancies"], 1)
        self.assertTrue(any(d.code == "UEL0801" for d in bag.items))
        stubs = list((self.root / "analysis" / "investigations").glob("*.uel.suggested"))
        self.assertEqual(len(stubs), 1)

    def test_prediction_validation_against_lock(self):
        res, bag = self._res()
        self.assertTrue(build(res, bag, verbose=False).ok())
        # w = 10 kN / 42 kN/mm = 0.238 mm ± 10%; measure far outside
        summary, bag2 = self._ingest(
            [{"target": "FitDeflection.outputs.w", "value": 0.5, "unit": "mm",
              "unc": {"kind": "abs", "value": 0.01}}]
        )
        self.assertEqual(summary["discrepancies"], 1)
        lock = Lock.load(self.root / "uel.lock")
        v = lock.nodes["FitDeflection"].run["validation"]["w"]
        self.assertEqual(v["verdict"], "outside_envelope")

    def test_as_built_serial_overlay_is_separate(self):
        self._ingest([{"target": "Fitting.mass", "value": 122.0, "unit": "g",
                       "unc": {"kind": "abs", "value": 0.5}}], serial="SN003")
        # base view untouched
        res_base, _ = self._res()
        self.assertEqual(res_base.doc.components()["Fitting"].quantities["mass"].value, 120.0)
        # serial view carries the measurement
        res_sn, _ = self._res(serial="SN003")
        self.assertEqual(res_sn.doc.components()["Fitting"].quantities["mass"].value, 122.0)
        self.assertEqual(res_sn.doc.components()["Fitting"].quantities["mass"].prov.kind, "measured")


if __name__ == "__main__":
    unittest.main()
