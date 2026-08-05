"""v0.3 verification contracts (ADR-0008): end-to-end through the real pipeline.

An expr oracle cross-checks a python 'tool' core; probes catch a wrong-physics
core that is numerically correct at the operating point; golden cases pin
behavior; the review dossier carries the evidence.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from uel.diagnostics import Bag
from uel.lockfile import Lock
from uel.project import load_project
from uel.resolver import resolve_project
from uel.scheduler import build

MODEL = """\
requirement R-1 {
  wind = 25 m/s
}

analysis Oracle {
  knowns {
    wind <- req.R-1.wind
  }
  params {
    k = 4.2 kg/m
  }
  core expr {
    moment = k * wind ^ 2
  }
  outputs {
    moment : N
  }
}

analysis Tool {
  knowns {
    wind <- req.R-1.wind
  }
  core python "tool.py" {
    tool "windsolve" "3.2.1"
  }
  verify moment against Oracle.outputs.moment within 5 %
  verify moment monotone with wind rising
  verify case "golden.json" within 1 %
  outputs {
    moment : N
  }
}
"""

TOOL_OK = """\
import json, sys
p = json.load(sys.stdin)
w = p["inputs"]["wind"]["si"]
json.dump({"outputs": {"moment": {"value": 4.2 * w * w, "unit": "N"}}}, sys.stdout)
"""

# wrong physics that agrees at the nominal operating point (w = 25):
# 4.2*(50-w)^2 == 4.2*w^2 exactly at w = 25 — only a probe can tell them apart.
TOOL_WRONG_PHYSICS = TOOL_OK.replace("4.2 * w * w", "4.2 * (50.0 - w) ** 2")

GOLDEN = '{"inputs": {"wind": {"value": 10, "unit": "m/s"}}, "expect": {"moment": {"value": 420, "unit": "N"}}}\n'


class VerifyContracts(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        (self.td / "model.uel").write_text(MODEL, encoding="utf-8")
        (self.td / "tool.py").write_text(TOOL_OK, encoding="utf-8")
        (self.td / "golden.json").write_text(GOLDEN, encoding="utf-8")

    def resolve(self, bag: Bag):
        return resolve_project(load_project(self.td, bag), bag)

    def test_contracts_pass_and_record_evidence(self):
        bag = Bag()
        res = self.resolve(bag)
        self.assertTrue(bag.ok())
        result = build(res, bag, verbose=False)
        self.assertTrue(result.ok(), [d.message for d in bag.errors])
        import json
        lock = json.loads((self.td / "uel.lock").read_text(encoding="utf-8"))
        recs = lock["nodes"]["Tool"]["run"]["verify"]
        self.assertEqual([r["ok"] for r in recs], [True, True])
        # and the against-check passes silently at check time
        from uel import contracts
        bag2 = Bag()
        res2 = self.resolve(bag2)
        contracts.check(res2, bag2, Lock.load(self.td / "uel.lock", bag2))
        self.assertFalse([d for d in bag2.items if d.code == "UEL0808"])

    def test_probe_catches_wrong_physics_that_matches_at_nominal(self):
        (self.td / "tool.py").write_text(TOOL_WRONG_PHYSICS, encoding="utf-8")
        bag = Bag()
        res = self.resolve(bag)
        result = build(res, bag, verbose=False)
        self.assertIn("Tool", result.failed)
        msgs = [d.message for d in bag.errors if d.code == "UEL0808"]
        # the cross-check CANNOT catch this (values agree at wind=25); the
        # monotone probe and the golden case both do
        self.assertTrue(any("monotone" in m for m in msgs), msgs)
        self.assertTrue(any("golden.json" in m for m in msgs), msgs)

    def test_against_catches_coefficient_drift(self):
        bag = Bag()
        res = self.resolve(bag)
        build(res, bag, verbose=False)
        (self.td / "tool.py").write_text(TOOL_OK.replace("4.2", "5.1"), encoding="utf-8")
        bag2 = Bag()
        res2 = self.resolve(bag2)
        result = build(res2, bag2, verbose=False)  # monotone/case still hold shape…
        from uel import contracts
        bag3 = Bag()
        res3 = self.resolve(bag3)
        contracts.check(res3, bag3, Lock.load(self.td / "uel.lock", bag3))
        hits = [d for d in bag3.items if d.code == "UEL0808" and d.severity == "error"]
        self.assertTrue(hits and "against" in hits[0].message)
        _ = result

    def test_pack_carries_the_evidence(self):
        bag = Bag()
        res = self.resolve(bag)
        build(res, bag, verbose=False)
        from uel.projections import pack
        bag2 = Bag()
        res2 = self.resolve(bag2)
        text = pack(res2, Lock.load(self.td / "uel.lock", bag2), "Tool")
        for needle in ("Review dossier — Tool", "windsolve", "monotone with wind rising",
                       "cross-check", "```python", "recipe "):
            self.assertIn(needle, text)
        # the oracle's dossier says verification is by construction
        text2 = pack(res2, Lock.load(self.td / "uel.lock", bag2), "Oracle")
        self.assertIn("by construction", text2)


if __name__ == "__main__":
    unittest.main()
