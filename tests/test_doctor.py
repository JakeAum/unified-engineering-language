"""`uel doctor` — the checkup (uel/doctor.py, diagnostic band UEL10xx).

The claims worth pinning, in the order they matter:

1. **It never files, writes, builds, or repairs anything.** Reporting upstream is
   an explicit decision, not a side effect of running an audit — the never-files
   rule from `0007-doctor-and-upstream-issues.md` §Framing. This is tested twice —
   behaviourally (the tree is byte-identical afterwards) and structurally (the
   module has no write or network surface at all), because it is the one property
   a future edit is most likely to break by accident.
2. **The report is self-authenticating.** Every hash a finding cites is a real
   prefix of something in `uel.lock` or recomputable with `uel hash`. A report
   nobody can check is a report nobody should believe, so the checkability is a
   test and not a promise in a docstring.
3. **Stale is distinguished from hand-edited**, exactly, and an honest stale
   report is never accused of tampering.
4. **The trust ledger classifies every executable node** and its totals close.
5. **`--strict` gates on errors only**, so it can be a CI step.

None of these tests may depend on build or projection artifacts that live under
`out/` in a working tree: `out/` is gitignored, so anything that assumes it exists
passes for the author and fails on a clean checkout. Tests that need a compiled
projection compile it themselves, into a temp copy.
"""

import contextlib
import io
import json
import re
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from uel import doctor as D
from uel.cli import main as _cli_main
from uel.diagnostics import CODES
from uel.hashing import graph_hash


def cli(*argv: str) -> int:
    """Run a CLI command with its stdout captured.

    Deliberate: a test suite that lets commands print into the CI log interleaves
    block-buffered stdout with unittest's line-buffered stderr, and the last line
    of the log stops being the thing that failed. That misreading is what made the
    v0.1.3 doctor's CI failure look like a build crash when what actually broke was
    four tests assuming `out/` exists on a clean checkout."""
    with contextlib.redirect_stdout(io.StringIO()):
        return _cli_main(list(argv))


REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"
ALL_EXAMPLES = ("apache-one", "ground-station", "ground-station-lc")

# A project sick in every way the doctor is supposed to notice at compile time:
# a stub standing in for analysis, a registered model with one hazard shrugged off
# and one unanswered, a rollup over a leaf with no mass, an input nothing feeds,
# and a target with nothing built to grade.
_SICK = """\
    model plate.kirchhoff_thin {
      hazard transverse_shear "thick plates: deflection underpredicted"
      hazard membrane_stiffening "large deflection: linear theory overpredicts stress"
    }

    component Rack : functional {
      port feed : electrical {
        direction in
        voltage: [22, 26 V]
        current: [0, 8 A]
      }
      budget mass <= 40 kg
      contains Panel
      contains Ballast
    }

    component Panel : functional {
      mass = 6 kg
    }

    component Ballast : functional {
      doc "no mass declared: the rollup stands on a hole"
    }

    analysis PanelBending {
      framing {
        model plate.kirchhoff_thin
        waive transverse_shear because "%s"
      }
      core stub {
        w_max = 2 mm
      }
      outputs {
        w_max : mm target <= 3 mm
      }
      judgment pending
    }
    """


class DoctorCase(unittest.TestCase):
    """Temp-directory plumbing shared by every case below."""

    def copy(self, name: str) -> Path:
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        root = td / name
        shutil.copytree(EXAMPLES / name, root)
        return root

    def sick(self, waiver: str = "n/a") -> Path:
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        (td / "model").mkdir()
        (td / "uel.toml").write_text(
            '[project]\nname = "sick"\nedition = "2026"\nmodel = ["model"]\n', encoding="utf-8")
        (td / "model" / "m.uel").write_text(textwrap.dedent(_SICK) % waiver, encoding="utf-8")
        return td

    def run_doctor(self, root: Path) -> D.Checkup:
        checkup, bag = D.run(root)
        self.assertEqual([d.code for d in bag.errors], [],
                         "fixture no longer resolves: " + bag.render())
        return checkup

    def codes(self, checkup: D.Checkup) -> set[str]:
        return {f.code for f in checkup.findings}

    def find(self, checkup: D.Checkup, code: str) -> list[D.Finding]:
        return [f for f in checkup.findings if f.code == code]

    def edit_lock(self, root: Path, mutate) -> None:
        p = root / "uel.lock"
        d = json.loads(p.read_text(encoding="utf-8"))
        mutate(d)
        p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TheDoctorNeverFilesAnything(DoctorCase):
    """The never-files rule's boundary: the doctor observes and prints. It never
    repairs, never commits, never builds, and never files. CI may run it; CI may
    not file."""

    @staticmethod
    def _snapshot(root: Path) -> dict[str, bytes]:
        return {str(p.relative_to(root)): p.read_bytes()
                for p in sorted(root.rglob("*")) if p.is_file()}

    def test_a_checkup_leaves_the_project_byte_identical(self):
        for name in ALL_EXAMPLES:
            with self.subTest(project=name):
                root = self.copy(name)
                before = self._snapshot(root)
                self.run_doctor(root)
                self.assertEqual(self._snapshot(root), before,
                                 "doctor modified the project it was auditing")

    def test_a_checkup_over_compiled_projections_still_writes_nothing(self):
        root = self.copy("apache-one")
        self.assertEqual(cli("project", "all", str(root)), 0)
        before = self._snapshot(root)
        self.run_doctor(root)
        self.assertEqual(self._snapshot(root), before)

    def test_the_module_has_no_filing_surface_at_all(self):
        """Structural, not behavioural: a future finding cannot accidentally
        acquire a way to phone home if the module never imports one."""
        src = (REPO / "uel" / "doctor.py").read_text(encoding="utf-8")
        for forbidden in ("subprocess", "urllib", "http.client", "socket", "smtplib",
                          "requests", "os.system", "popen"):
            self.assertNotIn(forbidden, src, f"doctor gained a {forbidden} surface")
        for writer in (".write_text(", ".write_bytes(", ".mkdir(", ".unlink(", "shutil."):
            self.assertNotIn(writer, src, f"doctor gained a filesystem write ({writer})")

    def test_the_structured_report_says_so_out_loud(self):
        obj = json.loads(D.to_json(self.run_doctor(self.copy("apache-one"))))
        self.assertIs(obj["files_nothing"], True)


class SelfAuthenticatingReport(DoctorCase):
    """Every claim cites the hash it came from, and every hash is real. The reader
    greps `uel.lock` (recipe / core-content / output hashes) or re-runs
    `uel hash --node` (node hashes) — no trust in the report required."""

    LOCK_LABELS = ("recipe", "core content", "output hash")

    def test_every_lock_derived_citation_is_a_real_prefix_of_the_lock(self):
        for name in ALL_EXAMPLES:
            with self.subTest(project=name):
                root = self.copy(name)
                lock_text = (root / "uel.lock").read_text(encoding="utf-8")
                checkup = self.run_doctor(root)
                cited = 0
                for f in checkup.findings:
                    for label, value in f.cites:
                        if label not in self.LOCK_LABELS or value == "—": continue
                        self.assertRegex(value, r"^[0-9a-f]{%d}$" % D.SHORT)
                        self.assertIn(value, lock_text,
                                      f"{f.code} cites {label} {value}, which is in no lock entry")
                        cited += 1
                self.assertGreater(cited, 0, "a report that cites nothing authenticates nothing")

    def test_every_ledger_row_cites_its_recipe_and_core_from_the_lock(self):
        root = self.copy("ground-station")
        lock_text = (root / "uel.lock").read_text(encoding="utf-8")
        checkup = self.run_doctor(root)
        self.assertTrue(checkup.ledger)
        for row in checkup.ledger:
            self.assertIn(row.recipe, lock_text, f"{row.node}: recipe {row.recipe} not in the lock")
            self.assertIn(row.core, lock_text, f"{row.node}: core hash {row.core} not in the lock")

    def test_node_hash_citations_recompute_with_uel_hash(self):
        """Hazard findings cite the model node's content hash, which is not in the
        lock — a reader recomputes it. So must this test."""
        from uel.calibration import apply_overlays
        from uel.diagnostics import Bag
        from uel.hashing import node_hash
        from uel.project import load_project
        from uel.resolver import resolve_project

        root = self.sick()
        checkup = self.run_doctor(root)
        bag = Bag()
        project = load_project(root, bag)
        res = resolve_project(project, bag)
        apply_overlays(res, "")
        known = {node_hash(n, project.tolerances)[7:7 + D.SHORT] for n in res.doc.nodes.values()}
        cited = [v for f in checkup.findings for k, v in f.cites
                 if k in ("model hash", "analysis hash", "component hash")]
        self.assertTrue(cited)
        for v in cited:
            self.assertIn(v, known)

    def test_the_header_stamps_the_graph_hash_the_kernel_computes(self):
        from uel.calibration import apply_overlays
        from uel.diagnostics import Bag
        from uel.project import load_project
        from uel.resolver import resolve_project

        root = self.copy("apache-one")
        checkup = self.run_doctor(root)
        bag = Bag()
        project = load_project(root, bag)
        res = resolve_project(project, bag)
        apply_overlays(res, "")
        self.assertEqual(checkup.graph,
                         graph_hash(res.doc, project.tolerances)[7:7 + D.SHORT])
        self.assertIn(checkup.graph, D.render(checkup))


class BuildState(DoctorCase):
    def test_a_project_with_no_lock_reports_every_node_never_built(self):
        root = self.copy("apache-one")
        (root / "uel.lock").unlink()
        checkup = self.run_doctor(root)
        never = self.find(checkup, "UEL1001")
        self.assertEqual(len(never), 7)
        self.assertEqual({f.severity for f in never}, {"warning"})
        self.assertNotIn("UEL1002", self.codes(checkup))

    def test_a_moved_input_makes_exactly_its_cone_stale(self):
        root = self.copy("apache-one")
        req = root / "model" / "requirements.uel"
        req.write_text(req.read_text().replace("V_NE = 34 m/s", "V_NE = 36 m/s"), encoding="utf-8")
        checkup = self.run_doctor(root)
        stale = self.find(checkup, "UEL1002")
        self.assertEqual([f.severity for f in stale], ["warning"])
        self.assertIn("WingFlutter", stale[0].message)
        self.assertIn("V_NE", stale[0].message)

    def test_a_failed_run_is_an_error_not_a_staleness_note(self):
        root = self.copy("apache-one")
        self.edit_lock(root, lambda d: d["nodes"]["WingFlutter"].__setitem__("status", "failed"))
        checkup = self.run_doctor(root)
        failed = self.find(checkup, "UEL1003")
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].severity, "error")
        self.assertIn("WingFlutter", failed[0].message)

    def test_a_lock_that_will_not_parse_is_said_once_and_loudly(self):
        """Every verdict is read out of the lock, so a broken one must not be
        allowed to look like a healthy project that has never been built."""
        root = self.copy("apache-one")
        (root / "uel.lock").write_text("{ not json", encoding="utf-8")
        checkup = self.run_doctor(root)
        f = self.find(checkup, "UEL1000")
        self.assertEqual(len(f), 1, "the lock is loaded more than once; say it once")
        self.assertEqual(f[0].severity, "error")
        self.assertEqual(cli("doctor", str(root), "--strict"), 1)

    def test_the_shipped_examples_are_all_fresh(self):
        for name in ALL_EXAMPLES:
            with self.subTest(project=name):
                codes = self.codes(self.run_doctor(self.copy(name)))
                self.assertEqual(codes & {"UEL1001", "UEL1002", "UEL1003"}, set())


class VerificationContracts(DoctorCase):
    def test_shipped_contracts_all_pass(self):
        checkup = self.run_doctor(self.copy("ground-station"))
        self.assertEqual(self.codes(checkup) & {"UEL1010", "UEL1011", "UEL1012"}, set())

    def test_a_recorded_verdict_that_failed_is_an_error(self):
        root = self.copy("ground-station")
        self.edit_lock(root, lambda d: d["nodes"]["EnclosureThermal"]["run"]["verify"][0]
                       .__setitem__("ok", False))
        f = self.find(self.run_doctor(root), "UEL1010")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].severity, "error")
        self.assertIn("verify case", f[0].message)

    def test_a_cross_check_is_re_derived_from_the_lock_not_replayed(self):
        """`against` contracts are lock-vs-lock; moving the oracle's value must
        flip the verdict without anything being re-run."""
        root = self.copy("ground-station")

        def wreck(d):
            o = d["nodes"]["WindLoadsOracle"]["outputs"]["gust_moment"]
            o["value"] = float(o["value"]) * 3.0

        self.edit_lock(root, wreck)
        f = [x for x in self.find(self.run_doctor(root), "UEL1010") if "against" in x.message]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].severity, "error")
        self.assertIn("agreement band", f[0].message)

    def test_a_contract_with_no_recorded_verdict_is_never_exercised(self):
        root = self.copy("ground-station")
        self.edit_lock(root, lambda d: d["nodes"]["PedestalModes"]["run"].pop("verify"))
        f = self.find(self.run_doctor(root), "UEL1012")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].severity, "warning")
        self.assertIn("monotone", f[0].message)
        self.assertIn("never been exercised", f[0].message)

    def test_a_cross_check_with_an_unbuilt_side_is_pending_not_failed(self):
        root = self.copy("ground-station")
        self.edit_lock(root, lambda d: d["nodes"]["WindLoadsOracle"]["outputs"].clear())
        checkup = self.run_doctor(root)
        pending = [f for f in self.find(checkup, "UEL1011") if "against" in f.message]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].severity, "info")
        self.assertNotIn("UEL1010", self.codes(checkup))


class TargetVerdicts(DoctorCase):
    def test_a_violated_target_is_an_error_citing_the_output_hash(self):
        root = self.copy("ground-station-lc")
        self.edit_lock(root, lambda d: d["nodes"]["LinkMargin"]["outputs"]["margin_db"]
                       .__setitem__("value", 1.0))
        f = self.find(self.run_doctor(root), "UEL1020")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].severity, "error")
        self.assertIn("VIOLATES", f[0].message)
        self.assertIn("output hash", dict(f[0].cites))

    def test_passing_on_the_nominal_with_the_band_across_the_line_is_a_warning(self):
        checkup = self.run_doctor(self.copy("ground-station-lc"))
        crossing = self.find(checkup, "UEL1021")
        self.assertEqual({f.severity for f in crossing}, {"warning"})
        self.assertEqual({m.split("'")[1].split(".")[0] for m in (f.message for f in crossing)},
                         {"SteptrackPointing", "LinkMargin"})

    def test_a_target_with_nothing_built_is_pending(self):
        f = self.find(self.run_doctor(self.sick()), "UEL1022")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].severity, "info")
        self.assertIn("PENDING", f[0].message)


class HazardDispositions(DoctorCase):
    def test_an_unanswered_hazard_is_reported_with_the_reason_it_kills(self):
        f = self.find(self.run_doctor(self.sick()), "UEL1030")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].severity, "warning")
        self.assertIn("membrane_stiffening", f[0].message)
        self.assertIn("linear theory overpredicts stress", f[0].message)

    def test_an_empty_waiver_is_an_error(self):
        f = self.find(self.run_doctor(self.sick(waiver="")), "UEL1031")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].severity, "error")
        self.assertIn("EMPTY", f[0].message)

    def test_a_boilerplate_waiver_is_a_warning(self):
        for shrug in ("n/a", "N/A.", "TBD", "not applicable", "negligible", "too small"):
            with self.subTest(waiver=shrug):
                f = self.find(self.run_doctor(self.sick(waiver=shrug)), "UEL1031")
                self.assertEqual(len(f), 1)
                self.assertEqual(f[0].severity, "warning")

    def test_a_real_argument_passes(self):
        argued = ("t/span = 1/80, comfortably thin; the Reissner-Mindlin correction at "
                  "that slenderness is under one percent of deflection")
        self.assertEqual(self.find(self.run_doctor(self.sick(waiver=argued)), "UEL1031"), [])

    def test_every_shipped_example_waives_with_an_argument(self):
        """The examples are the reference for what a waiver should look like; if
        one ever degrades into a shrug, this is where it shows up."""
        for name in ALL_EXAMPLES:
            with self.subTest(project=name):
                checkup = self.run_doctor(self.copy(name))
                self.assertEqual(self.find(checkup, "UEL1031"), [])
                self.assertEqual(self.find(checkup, "UEL1030"), [])


class UncertaintyBasis(DoctorCase):
    def test_an_opaque_core_asserts_every_band_it_returns(self):
        checkup = self.run_doctor(self.copy("apache-one"))
        asserted = {f.message.split("'")[1] for f in self.find(checkup, "UEL1050")}
        self.assertIn("SparStaticLimit.FoS", asserted)
        self.assertEqual({f.severity for f in self.find(checkup, "UEL1050")}, {"info"})
        self.assertEqual(checkup.unc_totals()["asserted"], 7)
        self.assertEqual(checkup.unc_totals()["propagated"], 0)

    def test_an_expr_core_propagates_and_is_never_accused(self):
        checkup = self.run_doctor(self.copy("ground-station-lc"))
        expr_nodes = {r.node for r in checkup.ledger if r.lang == "expr"}
        self.assertTrue(expr_nodes)
        for r in checkup.ledger:
            if r.lang == "expr":
                self.assertEqual(r.unc, "propagated")
        flagged = {f.message.split("'")[1].split(".")[0] for f in self.find(checkup, "UEL1050")}
        self.assertEqual(flagged & expr_nodes, set())

    def test_a_hard_band_derived_from_a_cal_input_is_flagged(self):
        """apache-one's spar core is the specimen: `root_moment` is declared
        `± cal` — not yet known — and the core returns `rel 0.05` anyway."""
        checkup = self.run_doctor(self.copy("apache-one"))
        cal = [f for f in self.find(checkup, "UEL1051") if "± cal" in f.message]
        self.assertEqual(len(cal), 3)  # FoS, root_stress, max_deflection
        self.assertEqual({f.severity for f in cal}, {"warning"})
        self.assertTrue(all("SparStaticLimit" in f.message for f in cal))

    def test_a_declared_band_that_the_lock_does_not_carry_is_a_warning(self):
        root = self.copy("apache-one")
        self.edit_lock(root, lambda d: d["nodes"]["SparDynamic"]["outputs"]
                       ["first_bending_mode"].pop("unc"))
        f = self.find(self.run_doctor(root), "UEL1052")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].severity, "warning")

    def test_a_ratio_is_not_taken_over_an_affine_or_level_scale(self):
        """`4 K` against `81.7 degC` is arithmetic without physics; the doctor must
        not manufacture a finding out of it."""
        self.assertIsNone(D._band(81.74, "degC", {"kind": "abs", "value": 4.0}).rel)
        self.assertIsNone(D._band(3.3, "dB", {"kind": "abs", "value": 0.5}).rel)
        self.assertAlmostEqual(D._band(200.0, "W", {"kind": "abs", "value": 20.0}).rel, 0.1)
        self.assertAlmostEqual(D._band(2.0, "", {"kind": "rel", "value": 0.05}).rel, 0.05)
        self.assertTrue(D._band(1.0, "N", {"kind": "cal"}).unquantified)


class TrustLedger(DoctorCase):
    def test_apache_one_rests_entirely_on_the_authors_word(self):
        checkup = self.run_doctor(self.copy("apache-one"))
        totals = checkup.totals()
        self.assertEqual(totals, {"construction": 0, "contract": 0, "word": 7,
                                  "placeholder": 0, "total": 7})
        self.assertEqual(len(self.find(checkup, "UEL1040")), 7)

    def test_the_ground_station_ledger_splits_three_ways(self):
        checkup = self.run_doctor(self.copy("ground-station"))
        by_node = {r.node: r.basis for r in checkup.ledger}
        self.assertEqual(by_node["LinkMargin"], "construction")
        self.assertEqual(by_node["WindLoads"], "contract")
        self.assertEqual(by_node["PedestalModes"], "contract")
        self.assertEqual(by_node["EnclosureThermal"], "contract")
        self.assertEqual(by_node["PowerBudget"], "word")
        t = checkup.totals()
        self.assertEqual(t, {"construction": 7, "contract": 3, "word": 6,
                             "placeholder": 0, "total": 16})

    def test_a_stub_is_a_placeholder_and_says_so(self):
        checkup = self.run_doctor(self.sick())
        self.assertEqual(checkup.totals()["placeholder"], 1)
        f = self.find(checkup, "UEL1080")
        self.assertEqual(len(f), 1)
        self.assertIn("placeholder", f[0].message)

    def test_the_totals_always_close_over_the_ledger(self):
        for name in ALL_EXAMPLES:
            with self.subTest(project=name):
                checkup = self.run_doctor(self.copy(name))
                t = checkup.totals()
                self.assertEqual(t["total"], len(checkup.ledger))
                self.assertEqual(
                    t["construction"] + t["contract"] + t["word"] + t["placeholder"], t["total"])
                self.assertEqual(sum(checkup.unc_totals().values()), t["total"])

    def test_the_ratio_is_rendered_not_only_tabulated(self):
        text = D.render(self.run_doctor(self.copy("ground-station")))
        self.assertIn("TRUST LEDGER", text)
        self.assertIn("verified by construction", text)
        self.assertIn("16 executable nodes", text)


class ModelHygiene(DoctorCase):
    def test_a_rollup_over_an_unvalued_leaf_is_reported(self):
        f = self.find(self.run_doctor(self.sick()), "UEL1070")
        self.assertEqual(len(f), 1)
        self.assertIn("Ballast", f[0].message)
        self.assertIn("Rack.mass", f[0].message)

    def test_an_unconnected_input_port_is_reported(self):
        f = self.find(self.run_doctor(self.sick()), "UEL1071")
        self.assertEqual(len(f), 1)
        self.assertIn("Rack.feed", f[0].message)

    def test_the_shipped_examples_have_neither(self):
        for name in ALL_EXAMPLES:
            with self.subTest(project=name):
                codes = self.codes(self.run_doctor(self.copy(name)))
                self.assertEqual(codes & {"UEL1070", "UEL1071"}, set())


class ProjectionIntegrity(DoctorCase):
    """Two diseases that look alike: a stale report is honest and out of date; a
    hand-edited one still claims its graph hash while its body no longer follows
    from it (spec §1.4). Every fixture here compiles its own projections — `out/`
    is gitignored and is never present on a clean checkout."""

    def project(self, name: str = "apache-one") -> Path:
        root = self.copy(name)
        self.assertEqual(cli("project", "all", str(root)), 0)
        self.assertTrue((root / "out" / "bom.md").is_file())
        return root

    def hand_edit(self, root: Path) -> str:
        bom = root / "out" / "bom.md"
        text = bom.read_text(encoding="utf-8")
        m = re.search(r"\| ([0-9]+\.[0-9]+) g \|", text)
        self.assertIsNotNone(m, "fixture drifted: the BOM no longer carries a gram mass")
        bom.write_text(text.replace(m.group(0), "| 999.9 g |", 1), encoding="utf-8")
        return m.group(1)

    def test_freshly_compiled_projections_are_clean(self):
        checkup = self.run_doctor(self.project())
        self.assertEqual(self.codes(checkup) & {"UEL1060", "UEL1061"}, set())
        self.assertTrue(any("projection integrity" in s for s in checkup.checked))

    def test_a_hand_edited_report_is_proven_not_guessed(self):
        root = self.project()
        self.hand_edit(root)
        checkup = self.run_doctor(root)
        f = self.find(checkup, "UEL1061")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].severity, "error")
        self.assertIn("out/bom.md", f[0].message)
        self.assertNotIn("UEL1060", self.codes(checkup))
        # the advice must point at the model, not at regenerating the evidence away
        self.assertIn("model", f[0].reason)
        self.assertIn("do not regenerate the evidence away", f[0].reason)

    def test_an_honestly_stale_report_is_not_accused_of_tampering(self):
        root = self.project()
        req = root / "model" / "requirements.uel"
        req.write_text(req.read_text().replace("V_NE = 34 m/s", "V_NE = 36 m/s"), encoding="utf-8")
        checkup = self.run_doctor(root)
        stale = self.find(checkup, "UEL1060")
        self.assertEqual(len(stale), 4)  # bom, icd, work, status
        self.assertEqual({f.severity for f in stale}, {"warning"})
        self.assertNotIn("UEL1061", self.codes(checkup))
        cites = dict(stale[0].cites)
        self.assertNotEqual(cites["graph claimed by report"], cites["graph now"])

    def test_an_unstamped_document_in_out_is_reported(self):
        root = self.project()
        (root / "out" / "status.md").write_text("# Status\n\nhand-written\n", encoding="utf-8")
        f = [x for x in self.find(self.run_doctor(root), "UEL1060") if "no graph stamp" in x.message]
        self.assertEqual(len(f), 1)

    def test_no_out_directory_is_not_a_finding(self):
        root = self.copy("apache-one")
        checkup = self.run_doctor(root)
        self.assertEqual(self.codes(checkup) & {"UEL1060", "UEL1061"}, set())
        self.assertFalse(any("projection integrity" in s for s in checkup.checked))


class DiagnosticCodes(DoctorCase):
    def test_doctor_stays_inside_its_band_and_registers_every_code(self):
        emitted = set()
        for name in ALL_EXAMPLES:
            emitted |= self.codes(self.run_doctor(self.copy(name)))
        emitted |= self.codes(self.run_doctor(self.sick(waiver="")))
        self.assertTrue(emitted)
        for code in emitted:
            self.assertRegex(code, r"^UEL10\d\d$", "doctor emitted outside the UEL10xx band")
            self.assertIn(code, CODES)

    def test_the_registry_and_the_source_agree_in_both_directions(self):
        """Every code doctor can construct is registered, and every UEL10xx code
        registered is one doctor can construct — no dead entries, no unregistered
        ones. Codes are stable API within an edition."""
        src = (REPO / "uel" / "doctor.py").read_text(encoding="utf-8")
        constructed = set(re.findall(r'Finding\(\s*"(UEL\d{4})"', src))
        self.assertTrue(constructed)
        for code in constructed:
            self.assertRegex(code, r"^UEL10\d\d$", "doctor constructs outside its band")
            self.assertIn(code, CODES)
        self.assertEqual({c for c in CODES if c.startswith("UEL10")}, constructed)

    def test_every_finding_carries_a_reason(self):
        """Program §4: a diagnostic without the reason the rule exists is a
        diagnostic an agent cannot act on."""
        for name in ALL_EXAMPLES:
            for f in self.run_doctor(self.copy(name)).findings:
                self.assertTrue(f.reason, f"{f.code} shipped without a reason")


class CliSurface(DoctorCase):
    def test_the_shipped_examples_pass_their_own_strict_checkup(self):
        for name in ALL_EXAMPLES:
            with self.subTest(project=name):
                root = self.copy(name)
                self.assertEqual(cli("doctor", str(root)), 0)
                self.assertEqual(cli("doctor", str(root), "--strict"), 0)

    def test_strict_gates_on_errors_only(self):
        root = self.copy("apache-one")
        self.edit_lock(root, lambda d: d["nodes"]["WingFlutter"].__setitem__("status", "failed"))
        self.assertEqual(cli("doctor", str(root)), 0)
        self.assertEqual(cli("doctor", str(root), "--strict"), 1)

    def test_warnings_alone_never_gate(self):
        root = self.copy("apache-one")
        (root / "uel.lock").unlink()  # every node never built: warnings, no errors
        checkup = self.run_doctor(root)
        self.assertTrue(checkup.by_severity("warning"))
        self.assertEqual(checkup.errors(), [])
        self.assertEqual(cli("doctor", str(root), "--strict"), 0)

    def test_json_carries_the_ledger_and_the_findings(self):
        root = self.copy("ground-station")
        obj = json.loads(D.to_json(self.run_doctor(root)))
        self.assertEqual(obj["trust"]["totals"]["total"], 16)
        self.assertEqual(len(obj["trust"]["ledger"]), 16)
        self.assertTrue(all({"code", "severity", "message", "reason"} <= set(f)
                            for f in obj["findings"]))
        self.assertEqual(cli("doctor", str(root), "--json"), 0)

    def test_a_project_that_does_not_resolve_is_refused_not_crashed(self):
        root = self.copy("apache-one")
        (root / "model" / "structure.uel").write_text("component {{{ broken", encoding="utf-8")
        checkup, bag = D.run(root)
        self.assertTrue(bag.errors)
        self.assertEqual(checkup.findings, [])
        self.assertEqual(cli("doctor", str(root)), 1)

    def test_doctor_is_registered_in_the_agent_briefing(self):
        from uel.agentdoc import briefing

        text = briefing(commands=["check", "doctor"])
        self.assertIn("doctor", text)
        self.assertIn("UEL10xx", text)


if __name__ == "__main__":
    unittest.main()
