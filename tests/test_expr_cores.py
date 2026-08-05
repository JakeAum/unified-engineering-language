"""v0.2 expression cores: end-to-end through the real pipeline.

Covers the three ADR-0005/0006/0007 claims with a live mini link budget:
kernel evaluation matches closed-form physics; interval bands enclose;
level normalization makes `52 dBm` == `22 dBW` for staleness; targets and
seam values re-verdict against the lock; domain errors fail the run.
"""

import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

from uel.diagnostics import Bag
from uel.lockfile import Lock
from uel.project import load_project
from uel.resolver import resolve_project
from uel.scheduler import build
from uel.staleness import compute

MODEL = """\
requirement LNK-1 {
  eirp_dbw = 22 dBW ± 1.5 dB
  freq = 8447.5 MHz
  max_range = 1650000 km
  data_rate = 2000 Hz
  required_ebn0_db = 4 dB
  min_margin_db = 3 dB
}

analysis Gt {
  core stub {
    g_over_t_dbk = 29.6 dB/K
  }
  outputs {
    g_over_t_dbk : dB/K
  }
}

analysis LinkMargin {
  framing {
    envelope {
      g_over_t_dbk in [20, 40 dB/K]
    }
  }
  knowns {
    eirp_dbw <- req.LNK-1.eirp_dbw
    freq <- req.LNK-1.freq
    max_range <- req.LNK-1.max_range
    data_rate <- req.LNK-1.data_rate
    required_ebn0_db <- req.LNK-1.required_ebn0_db
    g_over_t_dbk <- Gt.outputs.g_over_t_dbk
  }
  core expr {
    let lambda = const.c0 / freq
    let fspl_db = 2 * db(4 * const.pi * max_range / lambda)
    cn0_dbhz = eirp_dbw - fspl_db + g_over_t_dbk - db(const.k_B)
    margin_db = cn0_dbhz - db(data_rate) - required_ebn0_db
  }
  outputs {
    cn0_dbhz : dBHz ±
    margin_db : dB ± target >= req.LNK-1.min_margin_db
  }
}
"""


class ExprPipeline(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        (self.td / "model.uel").write_text(MODEL, encoding="utf-8")

    def resolve(self, bag: Bag):
        return resolve_project(load_project(self.td, bag), bag)

    def build_ok(self):
        bag = Bag()
        res = self.resolve(bag)
        self.assertTrue(bag.ok(), [str(d.message) for d in bag.errors])
        result = build(res, bag, verbose=False)
        self.assertTrue(result.ok(), [str(d.message) for d in bag.errors])
        return res, bag

    def lock_out(self, node: str, out: str):
        d = json.loads((self.td / "uel.lock").read_text(encoding="utf-8"))
        return d["nodes"][node]["outputs"][out]

    def test_matches_closed_form_physics(self):
        self.build_ok()
        c, f, R = 299792458.0, 8447.5e6, 1.65e9
        lam = c / f
        fspl = 20.0 * math.log10(4.0 * math.pi * R / lam)
        k_db = 10.0 * math.log10(1.380649e-23)
        cn0 = 22.0 - fspl + 29.6 - k_db
        margin = cn0 - 10.0 * math.log10(2000.0) - 4.0
        got = self.lock_out("LinkMargin", "margin_db")
        self.assertAlmostEqual(got["value"], margin, places=4)
        # the ±1.5 dB EIRP band flows straight through a linear-in-levels chain
        self.assertAlmostEqual(got["unc"]["value"], 1.5, places=6)

    def test_level_normalization_is_not_a_change(self):
        res, bag = self.build_ok()
        # 22 dBW == 52 dBm: rewriting the unit must not invalidate anything
        src = (self.td / "model.uel").read_text(encoding="utf-8")
        (self.td / "model.uel").write_text(
            src.replace("22 dBW ± 1.5 dB", "52 dBm ± 1.5 dB"), encoding="utf-8")
        bag2 = Bag()
        res2 = self.resolve(bag2)
        self.assertTrue(bag2.ok())
        rep = compute(res2, Lock.load(self.td / "uel.lock", bag2))
        self.assertEqual(rep.stale(), [], "dBm/dBW rename must be hash-invisible")

    def test_target_verdicts_follow_the_lock(self):
        from uel import contracts

        self.build_ok()
        bag = Bag()
        res = self.resolve(bag)
        contracts.check(res, bag, Lock.load(self.td / "uel.lock", bag))
        self.assertFalse([d for d in bag.items if d.code == "UEL0804" and d.severity == "error"])
        # raise the floor above the computed margin: the target flips to violated
        src = (self.td / "model.uel").read_text(encoding="utf-8")
        (self.td / "model.uel").write_text(
            src.replace("min_margin_db = 3 dB", "min_margin_db = 30 dB"), encoding="utf-8")
        bag3 = Bag()
        res3 = self.resolve(bag3)
        contracts.check(res3, bag3, Lock.load(self.td / "uel.lock", bag3))
        self.assertTrue([d for d in bag3.items if d.code == "UEL0804" and d.severity == "error"])

    def test_seam_value_checked_against_lock(self):
        from uel import envelopes

        self.build_ok()
        src = (self.td / "model.uel").read_text(encoding="utf-8")
        (self.td / "model.uel").write_text(
            src.replace("[20, 40 dB/K]", "[35, 40 dB/K]"), encoding="utf-8")
        bag = Bag()
        res = self.resolve(bag)
        envelopes.check_locked(res, bag, Lock.load(self.td / "uel.lock", bag))
        seam = [d for d in bag.items if d.code == "UEL0806"]
        self.assertEqual(len(seam), 1)
        self.assertIn("29.6", seam[0].message)

    def test_domain_error_fails_the_run(self):
        (self.td / "model.uel").write_text(
            """\
analysis Bad {
  core expr {
    x = sqrt((1 m^2) - (4 m^2))
  }
  outputs {
    x : m
  }
}
""", encoding="utf-8")
        bag = Bag()
        res = self.resolve(bag)
        self.assertTrue(bag.ok())
        result = build(res, bag, verbose=False)
        self.assertEqual(result.failed, ["Bad"])
        self.assertTrue(any(d.code == "UEL0703" for d in bag.errors))

    def test_stub_is_hash_addressed_too(self):
        self.build_ok()
        src = (self.td / "model.uel").read_text(encoding="utf-8")
        (self.td / "model.uel").write_text(
            src.replace("29.6 dB/K", "30.1 dB/K"), encoding="utf-8")
        bag = Bag()
        res = self.resolve(bag)
        rep = compute(res, Lock.load(self.td / "uel.lock", bag))
        self.assertEqual(rep.stale(), ["Gt", "LinkMargin"],
                         "a stub nominal edit invalidates exactly its cone")


class IntervalArithmetic(unittest.TestCase):
    def test_sin_interval_hits_extrema(self):
        from uel.expr import _sin

        lo, nom, hi = _sin((0.0, math.pi / 2, math.pi))
        self.assertAlmostEqual(hi, 1.0)  # pi/2 inside → max is exactly 1
        self.assertAlmostEqual(lo, 0.0, places=12)

    def test_division_by_spanning_interval_raises(self):
        from uel.expr import ExprEvalError, _div

        with self.assertRaises(ExprEvalError):
            _div((1.0, 1.0, 1.0), (-1.0, 0.5, 2.0))

    def test_even_power_of_signed_interval(self):
        from uel.expr import _pow

        lo, nom, hi = _pow((-2.0, 1.0, 3.0), 2)
        self.assertEqual((lo, hi), (0.0, 9.0))


if __name__ == "__main__":
    unittest.main()
