"""ADR-0007: the checkup, the doctored-report proof, and the upstream issue.

The claims worth pinning: a hand-edited projection is *proven*, not guessed,
and is told apart from an honestly stale one; kernel-class findings are
separated from the user's own drift; fingerprints are stable across runs and
machines so a defect files once; and nothing leaves the project — no filing, no
project data in the body — unless explicitly asked for. That last one matters
most: the upstream repository is public.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from uel import doctor as D
from uel.cli import main as cli_main
from uel.projections import INTEGRITY_PREFIX, seal, verify_seal
from uel.scaffold import init

REPO = Path(__file__).resolve().parent.parent
SLICE = REPO / "examples" / "apache-one"


class TestSeal(unittest.TestCase):
    def test_seal_is_verifiable_and_detects_any_edit(self):
        sealed = seal("# Report\n\n| mass | 470 g |\n")
        intact, recorded, recomputed = verify_seal(sealed)
        self.assertTrue(intact)
        self.assertEqual(recorded, recomputed)
        self.assertTrue(sealed.rstrip().startswith("#"))
        self.assertIn(INTEGRITY_PREFIX, sealed)

        edited = sealed.replace("470 g", "999 g")
        intact, recorded, recomputed = verify_seal(edited)
        self.assertFalse(intact)
        self.assertNotEqual(recorded, recomputed)

    def test_unsealed_text_reports_no_record(self):
        intact, recorded, _ = verify_seal("# Report\n\nno footer here\n")
        self.assertFalse(intact)
        self.assertEqual(recorded, "")

    def test_seal_is_stable(self):
        self.assertEqual(seal("a\nb\n"), seal("a\nb\n"))


class TestDoctorOnRealProject(unittest.TestCase):
    """The vertical slice is the honest patient: it is a real, built graph."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.root = Path(self.td) / "slice"
        shutil.copytree(SLICE, self.root)
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)

    def _codes(self, checkup) -> set[str]:
        return {f.code for f in checkup.findings}

    def _hand_edit_bom(self) -> None:
        """Edit a compiled report the way a person actually would: change a
        number in place. Asserts the target exists so a projection format change
        fails this test loudly instead of silently editing nothing."""
        bom = self.root / "out" / "bom.md"
        text = bom.read_text(encoding="utf-8")
        self.assertIn("455.2 g", text, "fixture drifted: pick a number that is in the BOM")
        bom.write_text(text.replace("455.2 g", "999.9 g"), encoding="utf-8")

    def test_healthy_project_is_clean(self):
        c = D.run(self.root)
        self.assertEqual(c.findings, [], D.render(c))
        self.assertIn("projection integrity", c.checked)
        self.assertIn("staleness honesty", c.checked)

    def test_doctored_report_is_caught_as_an_error(self):
        self._hand_edit_bom()
        c = D.run(self.root)
        doctored = [f for f in c.findings if f.code == "DOCTOR-102"]
        self.assertEqual(len(doctored), 1)
        self.assertEqual(doctored[0].severity, "error")
        self.assertEqual(doctored[0].audience, "user")
        # the advice must point at the model, not at regenerating the evidence away
        self.assertIn("model", doctored[0].advice)

    def test_stale_report_is_distinguished_from_a_doctored_one(self):
        req = self.root / "model" / "requirements.uel"
        req.write_text(req.read_text().replace("V_NE = 34 m/s", "V_NE = 36 m/s"), encoding="utf-8")
        c = D.run(self.root)
        codes = self._codes(c)
        self.assertIn("DOCTOR-103", codes)  # stale
        self.assertNotIn("DOCTOR-102", codes)  # not accused of tampering
        stale = next(f for f in c.findings if f.code == "DOCTOR-103")
        self.assertEqual(stale.severity, "warning")

    def test_corrupted_output_hash_is_kernel_class(self):
        lock = self.root / "uel.lock"
        d = json.loads(lock.read_text())
        out = d["nodes"]["PowerDraw"]["outputs"]["esc_loss"]
        out["value"] = float(out["value"]) * 3.0
        lock.write_text(json.dumps(d, indent=2), encoding="utf-8")
        c = D.run(self.root)
        f = next(f for f in c.findings if f.code == "DOCTOR-201")
        self.assertEqual(f.audience, "kernel")
        self.assertEqual(f.severity, "error")
        self.assertEqual(c.kernel(), [f])

    def test_doctor_never_raises_on_a_broken_project(self):
        (self.root / "model" / "structure.uel").write_text(
            "component Broken : functional { port p : nonexistent.domain }", encoding="utf-8")
        c = D.run(self.root)  # must not raise
        self.assertIsInstance(c.findings, list)

    def test_doctor_survives_a_project_that_is_not_one(self):
        empty = Path(self.td) / "not-a-project"
        empty.mkdir()
        c = D.run(empty)
        self.assertIsInstance(c.findings, list)


class TestFingerprints(unittest.TestCase):
    def test_stable_across_runs_and_independent_of_machine(self):
        a = D.Finding("DOCTOR-201", "kernel", "error", "t", "d",
                      evidence={"check": "x", "count": 1}, sensitive={"node": "MySecretPart"})
        b = D.Finding("DOCTOR-201", "kernel", "error", "different title", "different detail",
                      evidence={"check": "x", "count": 1}, sensitive={"node": "OtherPart"})
        # same defect, two users, two models: one fingerprint, one issue
        self.assertEqual(a.fingerprint(), b.fingerprint())
        c = D.Finding("DOCTOR-201", "kernel", "error", "t", "d", evidence={"check": "y"})
        self.assertNotEqual(a.fingerprint(), c.fingerprint())


class TestIssueRedaction(unittest.TestCase):
    def setUp(self):
        self.finding = D.Finding(
            "DOCTOR-204", "kernel", "error", "staleness under-invalidates", "detail",
            repro="uel stale <project>",
            evidence={"check": "staleness_under_invalidation", "count": 2},
            sensitive={"edges": ["req.CLASSIFIED.thrust->SecretAnalysis"]},
        )
        self.checkup = D.Checkup(findings=[self.finding], checked=["load+resolve"])

    def test_project_data_is_withheld_by_default(self):
        body = D.issue_body(self.checkup, [self.finding])
        self.assertNotIn("CLASSIFIED", body)
        self.assertNotIn("SecretAnalysis", body)
        self.assertIn("withheld", body)
        self.assertIn("staleness_under_invalidation", body)  # structure still travels
        self.assertIn(self.finding.fingerprint(), body)
        self.assertIn("uel stale", body)  # a repro, so triage can act

    def test_full_evidence_is_opt_in(self):
        body = D.issue_body(self.checkup, [self.finding], full=True)
        self.assertIn("SecretAnalysis", body)

    def test_title_names_the_defect(self):
        self.assertIn("staleness under-invalidates", D.issue_title([self.finding]))

    def test_json_report_withholds_by_default(self):
        obj = self.checkup.to_obj()
        self.assertEqual(obj["findings"][0]["withheld"], ["edges"])
        full = self.checkup.to_obj(full=True)
        self.assertEqual(full["findings"][0]["withheld"], {"edges": self.finding.sensitive["edges"]})


class TestCliSurface(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.root = Path(self.td) / "slice"
        shutil.copytree(SLICE, self.root)
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "uel", *args],
                              capture_output=True, text=True, cwd=str(REPO), timeout=180)

    def _hand_edit_bom(self) -> None:
        bom = self.root / "out" / "bom.md"
        text = bom.read_text(encoding="utf-8")
        self.assertIn("455.2 g", text, "fixture drifted: pick a number that is in the BOM")
        bom.write_text(text.replace("455.2 g", "999.9 g"), encoding="utf-8")

    def _corrupt_output_hash(self) -> None:
        lock = self.root / "uel.lock"
        d = json.loads(lock.read_text())
        out = d["nodes"]["PowerDraw"]["outputs"]["esc_loss"]
        out["value"] = float(out["value"]) * 3.0
        lock.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def test_doctor_reports_clean_and_exits_zero(self):
        r = self._run(["doctor", str(self.root)])
        self.assertEqual(r.returncode, 0)
        self.assertIn("clean", r.stdout)

    def test_strict_fails_ci_on_a_doctored_report(self):
        self._hand_edit_bom()
        self.assertEqual(self._run(["doctor", str(self.root)]).returncode, 0)
        strict = self._run(["doctor", str(self.root), "--strict"])
        self.assertEqual(strict.returncode, 1)
        self.assertIn("DOCTOR-102", strict.stdout)

    def test_issue_is_printed_not_filed(self):
        self._corrupt_output_hash()
        r = self._run(["doctor", str(self.root), "--issue"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("would file on", r.stdout)
        self.assertIn("DOCTOR-201", r.stdout)

    def test_nothing_to_file_when_only_user_findings(self):
        self._hand_edit_bom()
        r = self._run(["doctor", str(self.root), "--issue"])
        self.assertIn("nothing to file", r.stdout)

    def test_json_carries_a_ready_to_file_issue(self):
        self._corrupt_output_hash()
        obj = json.loads(self._run(["doctor", str(self.root), "--json"]).stdout)
        self.assertEqual(obj["summary"]["kernel"], 1)
        self.assertIn("issue", obj)
        self.assertTrue(obj["issue"]["body"])
        self.assertTrue(obj["issue"]["fingerprints"])
        self.assertEqual(obj["upstream"], D.UPSTREAM_DEFAULT)

    def test_upstream_is_configurable_from_the_manifest(self):
        manifest = self.root / "uel.toml"
        manifest.write_text(manifest.read_text() + '\n[doctor]\nupstream = "acme/uel-fork"\n',
                            encoding="utf-8")
        self.assertEqual(D.upstream_for(self.root), "acme/uel-fork")

    def test_scaffolded_project_passes_its_own_doctor(self):
        repo = Path(self.td) / "adopter"
        (repo / ".git").mkdir(parents=True)
        init(repo, name="adopter")
        self.assertEqual(cli_main(["build", str(repo)]), 0)
        c = D.run(repo)
        self.assertEqual(c.kernel(), [], D.render(c))


if __name__ == "__main__":
    unittest.main()
