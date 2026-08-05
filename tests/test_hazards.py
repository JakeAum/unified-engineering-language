"""v0.6 — the recursive-detail harness. Three mechanisms, each pinned:

1. Hazard obligations: a registered model's blind spots must be covered by some
   analysis or waived with a reason (UEL0510) — the checker asks the questions
   the solver cannot.
2. Convergence contracts: an iterating core must report the metric it promised,
   under threshold — silence is a failed run, not a clean one (UEL0808).
3. Sensitivity query: elasticities by perturbation — the square/cube laws made
   visible, superlinear inputs flagged.
"""

import json
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from uel.diagnostics import Bag
from uel.lockfile import Lock
from uel.project import load_project
from uel.resolver import resolve_project
from uel.scheduler import build, sensitivity


def _project(files: dict[str, str]) -> Path:
    td = Path(tempfile.mkdtemp())
    (td / "model").mkdir()
    (td / "uel.toml").write_text(
        '[project]\nname = "t"\nedition = "2026"\nmodel = ["model"]\n', encoding="utf-8")
    for rel, text in files.items():
        p = td / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text), encoding="utf-8")
    return td


def _check(td: Path) -> Bag:
    bag = Bag()
    res = resolve_project(load_project(td, bag), bag)
    from uel.checker import run_checks

    run_checks(res, bag, lock=True)
    return bag


_MODEL = """\
    model beam.euler_bernoulli {
      hazard lateral_torsional_buckling "Mcr falls with flange t^3 and unbraced L^2"
      hazard shear_deformation "short spans overpredict stiffness"
    }
    """

_USER = """\
    analysis Bracket {{
      framing {{
        model beam.euler_bernoulli
        {extra}
      }}
      core stub {{
        sigma = 100 MPa
      }}
      outputs {{
        sigma : MPa
      }}
      judgment pending
    }}
    """


class HazardObligations(unittest.TestCase):
    def _codes(self, extra: str, more_files: dict[str, str] | None = None):
        files = {"model/m.uel": _MODEL, "model/a.uel": _USER.format(extra=extra)}
        files.update(more_files or {})
        td = _project(files)
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        bag = _check(td)
        return [d for d in bag.items if d.code == "UEL0510"]

    def test_open_hazards_warn_per_hazard(self):
        diags = self._codes(extra="")
        self.assertEqual(len(diags), 2)
        self.assertTrue(all(d.severity == "warning" for d in diags))
        msgs = " ".join(d.message for d in diags)
        self.assertIn("lateral_torsional_buckling", msgs)
        self.assertIn("Mcr falls with flange t^3", msgs, "the model's why-text must reach the user")

    def test_waive_silences_with_reason(self):
        diags = self._codes(
            extra='waive shear_deformation because "span/depth = 40"\n'
                  '    waive lateral_torsional_buckling because "closed circular tube"')
        self.assertEqual(diags, [])

    def test_covering_analysis_discharges_project_wide(self):
        cover = """\
            analysis LtbCheck {
              framing {
                model structure.ltb_closed_form
                covers lateral_torsional_buckling
              }
              core stub {
                mcr_margin = 4
              }
              outputs {
                mcr_margin : dimensionless
              }
              judgment pending
            }
            """
        diags = self._codes(extra='waive shear_deformation because "span/depth = 40"',
                            more_files={"model/c.uel": cover})
        self.assertEqual(diags, [], "coverage by another analysis answers the obligation")

    def test_unregistered_model_imposes_nothing(self):
        src = _USER.format(extra="").replace("beam.euler_bernoulli", "beam.bespoke_v1")
        td = _project({"model/a.uel": src})
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        bag = _check(td)
        self.assertEqual([d for d in bag.items if d.code == "UEL0510"], [],
                         "registration is opt-in; an unregistered model obliges nothing")

    def test_stdlib_registration_reaches_every_project(self):
        # no project model node at all: the stdlib registry alone drives the
        # obligation — shipping domain knowledge that bites by default
        td = _project({"model/a.uel": _USER.format(extra="")})
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        diags = [d for d in _check(td).items if d.code == "UEL0510"]
        self.assertEqual(len(diags), 2, "stdlib beam.euler_bernoulli carries two hazards")
        self.assertIn("cube of flange thickness", " ".join(d.message for d in diags))


_ITER_CORE = '''\
    import json, sys
    p = json.load(sys.stdin)
    target = p["params"]["target"]["si"]
    x = target  # Newton iteration for sqrt(target): a genuinely iterating solver
    residual = 1.0
    n = 0
    while residual > 1e-12 and n < {cap}:
        x = 0.5 * (x + target / x)
        residual = abs(x * x - target) / target
        n += 1
    json.dump({{"outputs": {{"root": {{"value": x, "unit": ""}}}},
               "convergence": {{"residual": residual, "iterations": n}}}}, sys.stdout)
    '''

_ITER_ANALYSIS = """\
    analysis Root {{
      params {{
        target = 2
      }}
      core python "cores/iter.py"
      verify converged {contract}
      outputs {{
        root : dimensionless
      }}
      judgment pending
    }}
    """


class ConvergedContracts(unittest.TestCase):
    def _build(self, contract: str, cap: int):
        td = _project({
            "model/a.uel": _ITER_ANALYSIS.format(contract=contract),
            "cores/iter.py": _ITER_CORE.format(cap=cap),
        })
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        bag = Bag()
        res = resolve_project(load_project(td, bag), bag)
        self.assertTrue(bag.ok(), [d.message for d in bag.errors])
        result = build(res, bag, verbose=False)
        return td, bag, result

    def test_converged_run_passes_and_records_evidence(self):
        td, bag, result = self._build("residual <= 1e-9", cap=64)
        self.assertTrue(result.ok() and bag.ok(), [d.message for d in bag.errors])
        entry = json.loads((td / "uel.lock").read_text())["nodes"]["Root"]
        self.assertLessEqual(entry["run"]["convergence"]["residual"], 1e-9)
        rec = entry["run"]["verify"][0]
        self.assertTrue(rec["ok"])
        self.assertIn("residual", rec["contract"])

    def test_unconverged_run_is_a_failed_run(self):
        # two iterations cannot reach 1e-9: the value looks plausible, the
        # contract kills it anyway — the coarse-mesh scenario
        td, bag, result = self._build("residual <= 1e-9", cap=2)
        self.assertFalse(result.ok())
        self.assertTrue(any(d.code == "UEL0808" for d in bag.errors))
        entry = json.loads((td / "uel.lock").read_text())["nodes"]["Root"]
        self.assertEqual(entry["status"], "failed")

    def test_missing_metric_is_a_failed_run(self):
        td, bag, result = self._build("grid_indep <= 0.5", cap=64)
        self.assertFalse(result.ok())
        msgs = " ".join(d.message for d in bag.errors)
        self.assertIn("silence is not convergence", msgs)

    def test_converged_on_expr_core_is_rejected(self):
        td = _project({"model/a.uel": """\
            analysis E {
              core expr {
                y = 2 * (3 m)
              }
              verify converged residual <= 1e-9
              outputs {
                y : m
              }
              judgment pending
            }
            """})
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        bag = Bag()
        resolve_project(load_project(td, bag), bag)
        self.assertTrue(any(d.code == "UEL0107" and "closed-form" in d.message
                            for d in bag.errors))


class SensitivityQuery(unittest.TestCase):
    def test_square_law_flags_superlinear(self):
        td = _project({"model/a.uel": """\
            requirement R-001 {
              v = 20 m/s
              k = 0.5 kg/m
            }

            analysis Drag {
              knowns {
                v <- req.R-001.v
                k <- req.R-001.k
              }
              core expr {
                f = k * v ^ 2
              }
              outputs {
                f : N
              }
              judgment pending
            }
            """})
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        bag = Bag()
        res = resolve_project(load_project(td, bag), bag)
        self.assertTrue(bag.ok(), [d.message for d in bag.errors])
        self.assertTrue(build(res, bag, verbose=False).ok())
        text = sensitivity(res, "Drag", Lock.load(td / "uel.lock"), bag)
        lines = {ln.split()[0]: ln for ln in text.splitlines() if ln.strip() and ln.startswith("  ")}
        self.assertIn("+2.05", lines["v"], "square law: e = (1.05^2-1)/0.05")
        self.assertIn("▲", lines["v"])
        self.assertIn("+1.00", lines["k"])
        self.assertNotIn("▲", lines["k"], "linear inputs must not flag")
        self.assertIn("superlinear", text)

    def test_unbuilt_node_refuses(self):
        td = _project({"model/a.uel": """\
            analysis A {
              core stub {
                x = 1 m
              }
              outputs {
                x : m
              }
              judgment pending
            }
            """})
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        bag = Bag()
        res = resolve_project(load_project(td, bag), bag)
        text = sensitivity(res, "A", Lock.load(td / "uel.lock"), bag)
        self.assertIn("run `uel build` first", text)


if __name__ == "__main__":
    unittest.main()
