"""The economics scheduler (ADR-0010): attention ranking and information value.

The physics is the type checker; the economics is the scheduler. These tests
pin the *semantics* of both scores, not their absolute numbers — a weight may
be amended through the decision log, but the orderings below are claims about
what engineering value means and must survive that:

- a broken run outranks everything, because it is not a result at all;
- a violated acceptance target outranks a merely-eroded budget;
- a fresh node with an open obligation is still work, and rebuilding will not
  fix it;
- terms are normalized, so a wide graph does not out-shout a deep one;
- evidence age is measured inside the lock, never against wall-clock, so a
  ranking is reproducible tomorrow;
- a measurement that feeds a hot consumer beats one that feeds an equal number
  of cold ones (the v0.6 upgrade over a raw cone count);
- a budget's unvalued leaf is a candidate measurement even though it carries no
  quantity to be uncertain about — it is exactly the hole in the rollup.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from uel import economics as E
from uel.checker import run_checks
from uel.diagnostics import Bag
from uel.lockfile import Lock
from uel.project import load_project
from uel.resolver import resolve_project
from uel.scheduler import build
from uel.staleness import compute

REPO = Path(__file__).resolve().parent.parent

CORE = '''import json, sys
p = json.load(sys.stdin)
total = sum(v.get("si", 0.0) or 0.0 for v in p["inputs"].values())
total += sum(v.get("si", 0.0) or 0.0 for v in p["params"].values())
json.dump({"outputs": {"y": {"value": total, "unit": "m"}}}, sys.stdout)
'''

GEOM_CORE = '''import json, sys
json.load(sys.stdin)
json.dump({"outputs": {"mass": {"value": 95.0, "unit": "g"},
                       "volume": {"value": 1.0, "unit": "mm^3"}},
           "assertions": [{"name": "closed", "ok": True}]}, sys.stdout)
'''


def _project(files: dict[str, str], toml: str = '[project]\nname = "econ"\n') -> Path:
    td = Path(tempfile.mkdtemp())
    (td / "uel.toml").write_text(toml, encoding="utf-8")
    (td / "cores").mkdir()
    (td / "cores" / "n.py").write_text(CORE, encoding="utf-8")
    for rel, text in files.items():
        p = td / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text), encoding="utf-8")
    return td


def _load(td: Path, do_build: bool = False):
    """(res, rep, lock, rollups) for a project directory; optionally built first.

    Order matters: budget rollups read geometry masses out of the lock, so they
    must be computed *after* any build, exactly as the CLI does it."""
    bag = Bag()
    res = resolve_project(load_project(td, bag), bag)
    assert res is not None, bag.render()
    if do_build:
        build(res, Bag())
    rollups = run_checks(res, bag, lock=False) or {}
    return res, compute(res, Lock.load(res.project.lock_path)), \
        Lock.load(res.project.lock_path), rollups


def _rank(td: Path, do_build: bool = False, include_fresh: bool = True):
    res, rep, lock, rollups = _load(td, do_build)
    sig = E.signals(res, rep, lock, rollups)
    return E.rank(res, rep, lock, sig=sig, include_fresh=include_fresh), sig


def _terms(node) -> dict[str, float]:
    return {t.name: t.value for t in node.terms}


class BandPressure(unittest.TestCase):
    """The shared primitive: how much of a fence a band consumes."""

    def test_crossing_is_maximal(self):
        self.assertEqual(E.band_pressure((5.0, 12.0), 0.0, 10.0)[0], 1.0)
        self.assertEqual(E.band_pressure((-1.0, 5.0), 0.0, 10.0)[0], 1.0)

    def test_zero_lower_bound_is_one_sided(self):
        """`load in [0, 260 N*m]` fences a nonnegative quantity: it cannot exit
        below zero, so a tiny load is the safest case, not the hottest."""
        cold, _ = E.band_pressure((1.0, 1.0), 0.0, 100.0)
        hot, _ = E.band_pressure((99.0, 99.0), 0.0, 100.0)
        self.assertAlmostEqual(cold, 0.01)
        self.assertAlmostEqual(hot, 0.99)

    def test_two_sided_fence_presses_from_both_edges(self):
        """A genuinely two-sided fence (0 degC is 273.15 K in SI) is hot at both
        ends and coolest in the middle."""
        lo, _ = E.band_pressure((274.0, 274.0), 273.15, 373.15)
        mid, _ = E.band_pressure((323.0, 323.0), 273.15, 373.15)
        hi, _ = E.band_pressure((372.0, 372.0), 273.15, 373.15)
        self.assertGreater(lo, mid)
        self.assertGreater(hi, mid)
        self.assertLess(mid, 0.51)

    def test_unbounded_fence_exerts_nothing(self):
        self.assertEqual(E.band_pressure((5.0, 6.0), None, None)[0], 0.0)


class Terms(unittest.TestCase):
    """Each signal fires on its own evidence, and only on its own evidence."""

    def setUp(self):
        self.dirs: list[Path] = []

    def tearDown(self):
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def _mk(self, files, toml='[project]\nname = "econ"\n') -> Path:
        td = _project(files, toml)
        self.dirs.append(td)
        return td

    def test_requirement_trace_and_sole_source(self):
        """Serving a requirement is worth more when no other analysis does:
        shared evidence has redundancy, sole-sourced evidence has none."""
        td = self._mk({"m.uel": """\
            requirement R-1 { text "shall" \n  x = 1 m }
            analysis Sole {
              intent req.R-1 "the only witness"
              knowns { x <- req.R-1.x }
              core python "cores/n.py"
              outputs { y : m }
            }
            analysis SharedA {
              intent req.R-2 "one of two"
              knowns { x <- req.R-2.x }
              core python "cores/n.py"
              outputs { y : m }
            }
            analysis SharedB {
              intent req.R-2 "two of two"
              knowns { x <- req.R-2.x }
              core python "cores/n.py"
              outputs { y : m }
            }
            requirement R-2 { text "shall also" \n  x = 1 m }
            """})
        ranked, _ = _rank(td)
        by = {r.name: _terms(r) for r in ranked}
        self.assertEqual(by["Sole"]["serves"], 1.0)
        self.assertEqual(by["SharedA"]["serves"], 0.75)
        self.assertEqual(by["SharedB"]["serves"], 0.75)

    def test_no_intent_scores_no_requirement_term(self):
        td = self._mk({"m.uel": """\
            requirement R-1 { x = 1 m }
            analysis Free {
              knowns { x <- req.R-1.x }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        ranked, _ = _rank(td)
        self.assertEqual(_terms(ranked[0]).get("serves", 0.0), 0.0)

    def test_cone_is_normalized_not_counted(self):
        """A raw count makes the score unbounded and incomparable between
        graphs. The term is the *fraction* of the executable graph downstream,
        so a root node scores the same in a chain of 4 as in a chain of 8."""
        def chain(n: int) -> Path:
            src = ["requirement R { x = 1 m }", "analysis A0 {",
                   "  knowns { x <- req.R.x }", '  core python "cores/n.py"',
                   "  outputs { y : m }", "}"]
            for i in range(1, n):
                src += [f"analysis A{i} {{", f"  knowns {{ x <- A{i-1}.outputs.y }}",
                        '  core python "cores/n.py"', "  outputs { y : m }", "}"]
            return self._mk({"m.uel": "\n".join(src)})

        r4, _ = _rank(chain(4))
        r8, _ = _rank(chain(8))
        cone4 = next(_terms(r)["cone"] for r in r4 if r.name == "A0")
        cone8 = next(_terms(r)["cone"] for r in r8 if r.name == "A0")
        self.assertAlmostEqual(cone4, 1.0)
        self.assertAlmostEqual(cone8, 1.0)
        self.assertLessEqual(max(t.value for r in r8 for t in r.terms), 1.0)

    def test_stub_and_hazard_terms(self):
        """A placeholder core and an unanswered model hazard are both epistemic
        debt the staleness oracle cannot see."""
        td = self._mk({"m.uel": """\
            model plate.kirchhoff_thin {
              hazard transverse_shear "thick plates: deflection underpredicted"
              hazard membrane_stiffening "large deflection: linear theory overpredicts"
            }
            analysis Panel {
              framing {
                model plate.kirchhoff_thin
                waive transverse_shear because "t/span = 1/80, comfortably thin"
              }
              core stub { w = 2 mm }
              outputs { w : mm }
            }
            """})
        ranked, _ = _rank(td)
        t = _terms(ranked[0])
        self.assertEqual(t["stub"], 1.0)
        self.assertAlmostEqual(t["hazard"], 0.5)  # one of two answered
        self.assertIn("membrane_stiffening",
                      next(x.why for x in ranked[0].terms if x.name == "hazard"))

    def test_fence_term_uses_the_value_that_flows(self):
        """v0.6 sees the whole input vector: a fence on a known bound to an
        upstream *output* is pressed by the value in the lock, which the v0.1
        port (statics only) could not see."""
        td = self._mk({"m.uel": """\
            requirement R { x = 950 m }
            analysis Up {
              knowns { x <- req.R.x }
              core python "cores/n.py"
              outputs { y : m }
            }
            analysis Down {
              framing { envelope { a in [0, 1000 m] } }
              knowns { a <- Up.outputs.y }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        cold, _ = _rank(td)
        self.assertEqual(next(_terms(r).get("fence", 0.0) for r in cold if r.name == "Down"), 0.0)
        hot, _ = _rank(td, do_build=True)
        pressure = next(_terms(r)["fence"] for r in hot if r.name == "Down")
        self.assertAlmostEqual(pressure, 0.95, places=2)

    def test_margin_attaches_only_to_nodes_that_move_the_budget(self):
        """Budget erosion belongs to the geometry core whose locked mass is a
        rollup leaf (and its ancestors). An analysis that cannot change the
        number does not inherit its urgency — the cone term already carries
        'many things depend on me'."""
        td = self._mk({"m.uel": """\
            component Box : functional {
              budget mass <= 100 g
              contains Panel
            }
            component Panel : functional { }
            binding Panel -> panel_v1 : physical {
              geometry panel_geom
            }
            geometry panel_geom {
              params { t = 1 mm }
              core python "cores/geom.py"
              outputs { mass : g \n  volume : mm^3 }
            }
            analysis Elsewhere {
              params { q = 1 m }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        (td / "cores" / "geom.py").write_text(GEOM_CORE, encoding="utf-8")
        # before the build the leaf has no value at all: the budget has no
        # verdict until this node runs, which is the maximum a node can be worth
        cold, _ = _rank(td)
        self.assertEqual(next(_terms(r)["margin"] for r in cold if r.name == "panel_geom"), 1.0)
        ranked, _ = _rank(td, do_build=True)
        by = {r.name: _terms(r) for r in ranked}
        self.assertAlmostEqual(by["panel_geom"]["margin"], 0.95, places=2)
        self.assertEqual(by.get("Elsewhere", {}).get("margin", 0.0), 0.0)

    def test_rising_budget_outranks_a_settled_one_at_the_same_level(self):
        """Direction, not only level: a summed `<=` budget with a leaf still
        unvalued can only get worse, so it is scored as if further along."""
        settled = min(1.0, 0.6 * (1 + E.RISING_BUMP))
        self.assertGreater(settled, 0.6)
        self.assertLess(E.RISING_BUMP, 1.0, "a bump must never invert a real usage gap")

    def test_age_is_measured_inside_the_lock(self):
        """Never wall-clock: a ranking that changes because a day passed is not
        reproducible. The oldest evidence in the lock scores 1.0, the newest 0.0,
        and a node that never ran has no evidence at all — also 1.0."""
        ages = E._ages(Lock(nodes={
            "old": type("E", (), {"run": {"ts": "2026-01-01T00:00:00Z"}})(),
            "mid": type("E", (), {"run": {"ts": "2026-01-03T00:00:00Z"}})(),
            "new": type("E", (), {"run": {"ts": "2026-01-05T00:00:00Z"}})(),
        }), ["old", "mid", "new", "never"])
        self.assertEqual(ages["old"], 1.0)
        self.assertAlmostEqual(ages["mid"], 0.5)
        self.assertEqual(ages["new"], 0.0)
        self.assertEqual(ages["never"], 1.0)

    def test_age_of_an_all_at_once_lock_is_flat(self):
        same = {"run": {"ts": "2026-01-01T00:00:00Z"}}
        ages = E._ages(Lock(nodes={n: type("E", (), same)() for n in ("a", "b")}), ["a", "b"])
        self.assertEqual(set(ages.values()), {0.0})


class TargetsAndBreakage(unittest.TestCase):
    """The v0.6 verdicts the v0.1 port had no access to."""

    def setUp(self):
        self.dirs: list[Path] = []

    def tearDown(self):
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def _mk(self, body: str) -> Path:
        td = _project({"m.uel": body})
        self.dirs.append(td)
        return td

    def _target_project(self, floor: str, value: str, unc: str) -> Path:
        return self._mk(f"""\
            requirement R-1 {{ floor = {floor} }}
            analysis M {{
              intent req.R-1 "meet the floor"
              knowns {{ floor <- req.R-1.floor }}
              core expr {{ m_db = ({value}) {unc} }}
              outputs {{ m_db : dB ± target >= req.R-1.floor }}
            }}
            """)

    def test_pending_then_met_then_band_then_violated(self):
        """The four target verdicts are graded, not binary: finished-and-failed
        outranks a band across the line, which outranks evidence not yet in."""
        viol = self._target_project("3 dB", "1 dB", "")
        band = self._target_project("3 dB", "3.2 dB", "")
        met = self._target_project("3 dB", "9 dB", "")
        vals = {}
        for name, td in (("violated", viol), ("band", band), ("met", met)):
            ranked, _ = _rank(td, do_build=(name != "pending"))
            vals[name] = _terms(ranked[0]).get("target", 0.0)
        pending, _ = _rank(self._target_project("3 dB", "1 dB", ""), do_build=False)
        vals["pending"] = _terms(pending[0]).get("target", 0.0)
        self.assertEqual(vals["violated"], E.TARGET_VIOLATED)
        self.assertEqual(vals["pending"], E.TARGET_PENDING)
        self.assertEqual(vals["met"], 0.0)
        self.assertGreater(vals["violated"], vals["pending"])

    def test_band_crossing_is_between_met_and_violated(self):
        """Passing on the nominal while the ± band sits across the line is the
        situation a reviewer needs handed to them (ADR-0007)."""
        td = self._mk("""\
            requirement R-1 { floor = 3 dB }
            analysis M {
              knowns { floor <- req.R-1.floor }
              core expr { m_db = (3.2 dB) }
              outputs { m_db : dB ± target >= req.R-1.floor }
            }
            analysis Wide {
              knowns { w <- req.R-1.floor }
              core stub { m_db = 3.2 dB ± 1 dB }
              outputs { m_db : dB ± target >= req.R-1.floor }
            }
            """)
        ranked, _ = _rank(td, do_build=True)
        by = {r.name: _terms(r) for r in ranked}
        self.assertEqual(by["Wide"].get("target", 0.0), E.TARGET_BAND)
        self.assertEqual(by.get("M", {}).get("target", 0.0), 0.0)

    def test_a_broken_run_outranks_everything_else(self):
        """A failed run is not a result. It is loud, cheap signal and it blocks
        its whole cone, so it takes the top of the queue by construction."""
        td = self._mk("""\
            requirement R-1 { x = 1 m }
            analysis Broken {
              core python "cores/boom.py"
              params { q = 1 m }
              outputs { y : m }
            }
            analysis Rich {
              intent req.R-1 "everything but broken"
              framing { envelope { x in [0, 1.01 m] } }
              knowns { x <- req.R-1.x }
              core python "cores/n.py"
              outputs { y : m }
            }
            """)
        (td / "cores" / "boom.py").write_text(
            "import sys\nsys.stderr.write('exploded\\n')\nraise SystemExit(3)\n", encoding="utf-8")
        ranked, _ = _rank(td, do_build=True)
        self.assertEqual(ranked[0].name, "Broken")
        self.assertEqual(_terms(ranked[0])["broken"], 1.0)
        self.assertGreater(ranked[0].score, ranked[1].score)

    def test_fresh_node_with_an_open_obligation_is_still_work(self):
        """`--all`: rebuilding cannot fix a violated target, an uncovered
        hazard or a stub, so the staleness oracle alone would call this done."""
        td = self._mk("""\
            requirement R-1 { floor = 9 dB }
            analysis M {
              intent req.R-1 "meet the floor"
              knowns { floor <- req.R-1.floor }
              core expr { m_db = (1 dB) }
              outputs { m_db : dB ± target >= req.R-1.floor }
            }
            """)
        res, rep, lock, rollups = _load(td, do_build=True)
        self.assertEqual(rep.stale(), [], "the graph is fully built")
        sig = E.signals(res, rep, lock, rollups)
        self.assertEqual(E.rank(res, rep, lock, sig=sig), [], "no stale frontier")
        wide = E.rank(res, rep, lock, sig=sig, include_fresh=True)
        self.assertEqual([r.name for r in wide], ["M"])
        self.assertEqual(_terms(wide[0])["target"], E.TARGET_VIOLATED)


class Ordering(unittest.TestCase):
    """What the queue means, independent of the exact weights."""

    def setUp(self):
        self.dirs: list[Path] = []

    def tearDown(self):
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def test_frontier_marks_what_is_buildable_now(self):
        """`frontier` is orthogonal to value: it says what an agent can act on
        right now without building anything else first."""
        td = _project({"m.uel": """\
            analysis Up {
              params { q = 1 m }
              core python "cores/n.py"
              outputs { y : m }
            }
            analysis Down {
              knowns { a <- Up.outputs.y }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        self.dirs.append(td)
        ranked, _ = _rank(td, include_fresh=False)
        by = {r.name: r for r in ranked}
        self.assertTrue(by["Up"].frontier)
        self.assertFalse(by["Down"].frontier)

    def test_ties_break_toward_upstream(self):
        """Equal-value work is offered in buildable order. Zeta and Alpha are
        tuned to the same score by different routes (Zeta holds up the graph,
        Alpha carries the requirement); topological order decides, so the answer
        is Zeta — a plain name sort would say Alpha."""
        td = _project({"m.uel": """\
            requirement R-1 { text "shall" \n  x = 1 m }
            analysis Zeta {
              framing { envelope { q in [0, 5 m] } }
              params { q = 1 m }
              core python "cores/n.py"
              outputs { y : m }
            }
            analysis Alpha {
              intent req.R-1 "sole witness"
              knowns { a <- Zeta.outputs.y \n    x <- req.R-1.x }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        self.dirs.append(td)
        ranked, _ = _rank(td, include_fresh=False)
        self.assertEqual(len(ranked), 2)
        self.assertAlmostEqual(ranked[0].score, ranked[1].score, places=9,
                               msg="fixture must produce a genuine tie")
        self.assertEqual([r.name for r in ranked], ["Zeta", "Alpha"])

    def test_score_is_the_sum_of_the_reported_terms(self):
        """The breakdown is the arithmetic, not a commentary on it: an agent
        that adds the shown contributions must land on the shown score."""
        td = _project({"m.uel": """\
            requirement R-1 { x = 950 m }
            analysis A {
              intent req.R-1 "hot and load-bearing"
              framing { envelope { x in [0, 1000 m] } }
              knowns { x <- req.R-1.x }
              core python "cores/n.py"
              outputs { y : m }
            }
            analysis B {
              knowns { a <- A.outputs.y }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        self.dirs.append(td)
        ranked, _ = _rank(td)
        for r in ranked:
            self.assertAlmostEqual(r.score, sum(t.contribution for t in r.terms), places=9)
            for t in r.terms:
                self.assertAlmostEqual(t.contribution, t.value * E.WEIGHT[t.name], places=9)
                self.assertGreater(t.value, 0.0, "zero terms are not reported as reasons")

    def test_weight_table_is_the_single_source_of_truth(self):
        self.assertEqual(sorted(E.WEIGHT), sorted(t.name for t in E.TERMS))
        self.assertEqual(len({t.name for t in E.TERMS}), len(E.TERMS))
        self.assertTrue(all(t.weight > 0 and t.doc for t in E.TERMS))


class InformationValue(unittest.TestCase):
    """Which single test to run next, against a slow oracle."""

    def setUp(self):
        self.dirs: list[Path] = []

    def tearDown(self):
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def _values(self, files, do_build=False):
        td = _project(files)
        self.dirs.append(td)
        res, rep, lock, rollups = _load(td, do_build)
        sig = E.signals(res, rep, lock, rollups)
        return E.info_value(res, rep, lock, sig=sig), sig, td

    def test_declared_exact_values_are_not_candidates(self):
        """Info-value ranks *declared* ignorance. A value declared exact offers
        a measurement nothing to remove — and cannot see the unmodeled."""
        vals, _, _ = self._values({"m.uel": """\
            requirement R { exact = 5 m \n  vague = 5 m ± cal }
            analysis A {
              knowns { e <- req.R.exact \n    v <- req.R.vague }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        targets = {m.target for m in vals}
        self.assertIn("req.R.vague", targets)
        self.assertNotIn("req.R.exact", targets)

    def test_consumer_weight_beats_a_raw_cone_count(self):
        """The v0.6 upgrade over the v0.1 port: two quantities with identical
        ignorance and identical cone size rank by *what their consumers are
        worth*, so tightening a band that feeds a requirement-bearing, fence-hot
        analysis outranks tightening one that feeds a node nobody waits on."""
        vals, _, _ = self._values({"m.uel": """\
            requirement R-1 { text "shall" \n  hot = 950 m ± cal \n  cold = 950 m ± cal }
            analysis Hot {
              intent req.R-1 "load-bearing"
              knowns { x <- req.R-1.hot }
              core python "cores/n.py"
              outputs { y : m }
            }
            analysis Cold {
              knowns { x <- req.R-1.cold }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        by = {m.target: m for m in vals}
        self.assertEqual(by["req.R-1.hot"].cone, by["req.R-1.cold"].cone)
        self.assertEqual(by["req.R-1.hot"].tightening, by["req.R-1.cold"].tightening)
        self.assertGreater(by["req.R-1.hot"].consumer_weight, by["req.R-1.cold"].consumer_weight)
        self.assertGreater(by["req.R-1.hot"].value, by["req.R-1.cold"].value)
        self.assertEqual(vals[0].target, "req.R-1.hot")

    def test_a_band_across_a_fence_is_the_decisive_measurement(self):
        """The most a single contact with a slow oracle can buy is a decision."""
        vals, _, _ = self._values({"m.uel": """\
            requirement R { straddles = 1000 m ± 10 % \n  inside = 100 m ± 10 % }
            analysis A {
              framing { envelope { s in [0, 1050 m] \n    i in [0, 1050 m] } }
              knowns { s <- req.R.straddles \n    i <- req.R.inside }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        by = {m.target: m for m in vals}
        self.assertEqual(by["req.R.straddles"].pressure, 1.0)
        self.assertLess(by["req.R.inside"].pressure, 0.2)
        self.assertGreater(by["req.R.straddles"].value, by["req.R.inside"].value)

    def test_an_unvalued_budget_leaf_is_a_candidate(self):
        """v0.6-only: a leaf with no declared mass carries no band to be
        uncertain about, so the v0.1 port could not see it — yet it is exactly
        the hole that makes the rollup indeterminate."""
        vals, _, _ = self._values({"m.uel": """\
            component Box : functional {
              budget mass <= 100 g
              contains Known
              contains Hole
            }
            component Known : physical { mass = 40 g }
            component Hole : physical { }
            analysis A {
              params { q = 1 m }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        by = {m.target: m for m in vals}
        self.assertIn("Hole.mass", by)
        self.assertEqual(by["Hole.mass"].kind, "unvalued")
        self.assertEqual(by["Hole.mass"].pressure, 1.0)
        self.assertEqual(vals[0].target, "Hole.mass")

    def test_value_is_the_product_the_report_prints(self):
        vals, _, _ = self._values({"m.uel": """\
            requirement R { x = 950 m ± cal }
            analysis A {
              framing { envelope { x in [0, 1000 m] } }
              knowns { x <- req.R.x }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        for m in vals:
            self.assertAlmostEqual(
                m.value, m.tightening * (1 + m.consumer_weight) * (1 + m.pressure), places=9)

    def test_advisories(self):
        """UEL0902 fires when a graph declares no ignorance at all; UEL0903 names
        the measurements that would settle a verdict rather than refine one."""
        vals, sig, _ = self._values({"m.uel": """\
            requirement R { x = 5 m }
            analysis A {
              knowns { x <- req.R.x }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        bag = Bag()
        E.advise(sig, [], vals, bag)
        self.assertEqual([d.code for d in bag.items], ["UEL0902"])
        self.assertTrue(all(d.reason for d in bag.items))

        vals2, sig2, _ = self._values({"m.uel": """\
            requirement R { x = 1000 m ± 10 % }
            analysis A {
              framing { envelope { x in [0, 1050 m] } }
              knowns { x <- req.R.x }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        bag2 = Bag()
        E.advise(sig2, [], vals2, bag2)
        self.assertIn("UEL0903", [d.code for d in bag2.items])

    def test_unranked_stale_work_is_called_out(self):
        """UEL0901: invalid, but nothing depends on it and it serves nothing.
        Work with no linked failure is presumptively dead (program §5.3)."""
        td = _project({"m.uel": """\
            analysis Orphan {
              params { q = 1 m }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        self.dirs.append(td)
        ranked, sig = _rank(td, include_fresh=False)
        self.assertEqual([r.name for r in ranked], ["Orphan"])
        self.assertEqual(ranked[0].score, 0.0)
        bag = Bag()
        E.advise(sig, ranked, None, bag)
        self.assertEqual([d.code for d in bag.items], ["UEL0901"])

    def test_advise_distinguishes_none_from_empty(self):
        """`values=None` means the measurement side was not computed on this
        run, which is not the same as finding no candidates."""
        _, sig, _ = self._values({"m.uel": """\
            requirement R { x = 5 m }
            analysis A {
              knowns { x <- req.R.x }
              core python "cores/n.py"
              outputs { y : m }
            }
            """})
        bag = Bag()
        E.advise(sig, [], None, bag)
        self.assertEqual(bag.items, [])


class CliSurface(unittest.TestCase):
    """End to end through the real CLI, against the shipped examples."""

    def _run(self, *args) -> tuple[int, str]:
        p = subprocess.run([sys.executable, "-m", "uel", *args], cwd=REPO,
                           capture_output=True, text=True)
        return p.returncode, p.stdout

    def test_stale_rank_json_carries_the_weight_table_and_terms(self):
        rc, out = self._run("stale", "--rank", "--all", "--json", "examples/ground-station-lc")
        self.assertEqual(rc, 0, out)
        obj = json.loads(out)
        self.assertEqual([t["term"] for t in obj["terms"]], [t.name for t in E.TERMS])
        self.assertTrue(obj["ranked"], "the LC excursion carries standing obligations")
        first = obj["ranked"][0]
        self.assertAlmostEqual(first["score"], sum(t["contribution"] for t in first["terms"]),
                               places=2)
        scores = [r["score"] for r in obj["ranked"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_stale_rank_names_the_band_crossing_target(self):
        """The LC excursion's declared thinness (TRADE.md) is a computed warning
        in v0.6; the scheduler must surface it as work, not leave it in a log."""
        rc, out = self._run("stale", "--rank", "--all", "examples/ground-station-lc")
        self.assertEqual(rc, 0, out)
        self.assertIn("LinkMargin", out)
        self.assertIn("band crosses it", out)

    def test_info_value_ranks_and_explains_one_candidate(self):
        rc, out = self._run("query", "info-value", "examples/apache-one")
        self.assertEqual(rc, 0, out)
        self.assertIn("run next: req.STR-014.root_moment", out)
        rc, detail = self._run("query", "info-value", "req.STR-014.root_moment",
                               "examples/apache-one")
        self.assertEqual(rc, 0, detail)
        self.assertIn("rank 1 of", detail)
        self.assertIn("calibration-pending", detail)

    def test_info_value_json_and_unknown_target(self):
        rc, out = self._run("query", "info-value", "examples/ground-station", "--json")
        self.assertEqual(rc, 0, out)
        obj = json.loads(out)
        vals = [m["value"] for m in obj["measurements"]]
        self.assertEqual(vals, sorted(vals, reverse=True))
        rc, out = self._run("query", "info-value", "req.NOPE.x", "examples/apache-one")
        self.assertEqual(rc, 0, out)
        self.assertIn("not a candidate measurement", out)

    def test_plain_stale_is_unchanged_by_the_ranking_flag(self):
        rc, out = self._run("stale", "examples/apache-one")
        self.assertEqual(rc, 0, out)
        self.assertIn("all 7 executable nodes fresh", out)

    def test_a_red_graph_is_said_out_loud(self):
        """Neither query gates — but ranking work on a graph the checker rejects
        is ranking the wrong graph, and an agent must be told so."""
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        shutil.copytree(REPO / "examples" / "apache-one", td / "p")
        (td / "p" / "model" / "bad.uel").write_text(
            "analysis Nope {\n  knowns {\n    x <- req.MISSING.q\n  }\n}\n", encoding="utf-8")
        for cmd in (("stale", "--rank", str(td / "p")),
                    ("query", "info-value", str(td / "p"))):
            rc, out = self._run(*cmd)
            self.assertEqual(rc, 0, out)
            self.assertIn("compile error(s) in this graph", out, f"{cmd} stayed silent")
        rc, out = self._run("stale", "--rank", "--json", str(td / "p"))
        self.assertEqual(json.loads(out)["errors"], 1)


if __name__ == "__main__":
    unittest.main()
