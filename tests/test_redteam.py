"""Red-team regression tests (program §2.2, risk R4): attacks on the gate that
were found and fixed, pinned so they stay fixed."""

import shutil
import tempfile
import unittest
from pathlib import Path

from uel.checker import run_checks
from uel.diagnostics import Bag
from uel.hashing import _sig_round, quantize_in_unit, quantize_si
from uel.project import TolerancePolicy, load_project
from uel.resolver import resolve_project
from uel.scheduler import build


def _proj(root: Path, model: str, cores: dict[str, str] | None = None,
          toml: str = '[project]\nname = "rt"\n') -> None:
    (root / "model").mkdir(parents=True)
    (root / "uel.toml").write_text(toml)
    (root / "model" / "m.uel").write_text(model)
    for name, text in (cores or {}).items():
        (root / "cores").mkdir(exist_ok=True)
        (root / "cores" / name).write_text(text)


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.root = Path(self.td)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def check(self):
        bag = Bag()
        project = load_project(self.root, bag)
        res = resolve_project(project, bag) if not bag.errors else None
        if res is not None:
            run_checks(res, bag, lock=False)
        return res, bag

    def codes(self, bag):
        return [d.code for d in bag.items]


class TestHashingEquivalence(unittest.TestCase):
    def test_unit_rename_is_not_a_change(self):
        pol = TolerancePolicy()
        self.assertEqual(quantize_in_unit(850.0, "mm", pol), quantize_in_unit(0.85, "m", pol))
        self.assertEqual(quantize_in_unit(1.5, "kN", pol), quantize_in_unit(1500.0, "N", pol))

    def test_sig_round_idempotent(self):
        for v in (0.1, 1.0 / 3.0, 123456.789, 1e-30, -273.15, 9.999999999):
            once = _sig_round(v, 1e-6)
            self.assertEqual(once, _sig_round(once, 1e-6), v)

    def test_grid_quantization_idempotent(self):
        mass_dim = (1, 0, 0, 0, 0, 0, 0, 0)
        pol = TolerancePolicy(abs_tol={mass_dim: 1e-4})  # 0.1 g grid on mass
        once = quantize_si(0.45287000579, mass_dim, pol)
        self.assertEqual(once, quantize_si(once, mass_dim, pol))
        # quantize_in_unit normalizes into SI space (850 mm -> 0.85 m); its
        # contract is SI-out — the identity object stores dim, not unit
        self.assertEqual(quantize_in_unit(452.87000579, "g", pol), once)


class TestNonFiniteOutputs(Base):
    def test_nan_output_is_a_failed_run_not_a_crash(self):
        _proj(self.root, 'analysis A {\n  core python "cores/a.py"\n  outputs { x : m }\n}\n',
              {"a.py": 'import json,sys; json.load(sys.stdin); '
                       'json.dump({"outputs":{"x":{"value":float("nan"),"unit":"m"}}}, sys.stdout)'})
        res, bag = self.check()
        self.assertTrue(bag.ok())
        result = build(res, bag, verbose=False)
        self.assertEqual(result.failed, ["A"])
        self.assertIn("UEL0704", self.codes(bag))


class TestNamespaceCollisions(Base):
    def test_port_quantity_collision_rejected(self):
        _proj(self.root, 'component C : physical {\n  port mass : electrical\n  mass = 5 kg\n}\n')
        _, bag = self.check()
        self.assertTrue(any(d.code == "UEL0201" and "both a port and a quantity" in d.message
                            for d in bag.items))

    def test_reserved_namespaces_rejected(self):
        _proj(self.root, 'component lib : functional { }\n\ncomponent req : functional { }\n')
        _, bag = self.check()
        reserved = [d for d in bag.items if d.code == "UEL0201" and "reserved" in d.message]
        self.assertEqual(len(reserved), 2)


class TestContainsCount(Base):
    def test_zero_count_rejected(self):
        _proj(self.root, 'component A : functional {\n  contains B x 0\n}\n\ncomponent B : physical {\n  mass = 1 g\n}\n')
        _, bag = self.check()
        self.assertIn("UEL0107", self.codes(bag))


class TestDuplicateConnectionsDoNotDoubleCount(Base):
    def test_net_draw_counts_ports_once(self):
        model = (
            'component bus : physical {\n'
            '  port out : electrical { direction out\n    current: [0, 50 A] }\n'
            '}\n\n'
            'component load : physical {\n'
            '  port in : electrical { direction in\n    current: [0, 40 A] }\n'
            '}\n\n'
            'connect bus.out -> load.in\n'
            'connect bus.out -> load.in\n'
        )
        _proj(self.root, model)
        _, bag = self.check()
        # 40 A drawn once from 50 A: no UEL0403 even with the duplicate edge
        self.assertNotIn("UEL0403", [d.code for d in bag.errors])


if __name__ == "__main__":
    unittest.main()
