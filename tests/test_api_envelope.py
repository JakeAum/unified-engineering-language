"""The machine-facing door: envelope shape and exit-code discipline.

These cases exist to keep two promises that a machine caller cannot verify for
itself: that stdout under `--json` is always exactly one parseable envelope, and
that "your model is wrong" (1) is never confused with "I could not run" (3).
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from uel import api, cli
from uel.diagnostics import Bag

class TestEnvelope(unittest.TestCase):
    def test_shape(self) -> None:
        bag = Bag()
        env = api.envelope("check", bag, result={"nodes": 75})
        self.assertEqual(set(env), {"uel", "diagnostics", "result"})
        head = env["uel"]
        self.assertEqual(head["protocol"], api.PROTOCOL)
        self.assertEqual(head["command"], "check")
        self.assertTrue(head["ok"])
        self.assertEqual(env["result"], {"nodes": 75})
        self.assertEqual(env["diagnostics"], [])

    def test_ok_mirrors_error_severity(self) -> None:
        """`ok` must track error-severity only — a warning is not a rejection."""
        bag = Bag()
        bag.warning("UEL0406", "an 'in' port is never connected")
        self.assertTrue(api.envelope("check", bag)["uel"]["ok"])
        bag.error("UEL0403", "worst-case draw exceeds declared supply")
        self.assertFalse(api.envelope("check", bag)["uel"]["ok"])

    def test_always_present_keys(self) -> None:
        """`diagnostics` and `result` are never absent, so a caller need not
        branch before indexing them."""
        env = api.envelope("stale")
        self.assertEqual(env["diagnostics"], [])
        self.assertEqual(env["result"], {})

    def test_emit_is_exactly_one_object(self) -> None:
        buf = io.StringIO()
        bag = Bag()
        bag.error("UEL0501", "assumed range extends above the guaranteed fence")
        api.emit("check", bag, stream=buf)
        parsed = json.loads(buf.getvalue())  # raises if not exactly one object
        self.assertFalse(parsed["uel"]["ok"])
        self.assertEqual(parsed["diagnostics"][0]["code"], "UEL0501")

class TestExitCodeDiscipline(unittest.TestCase):
    """The 1-vs-3 split, which is the whole reason this module exists."""

    def setUp(self) -> None:
        """Swallow the stderr these cases deliberately provoke.

        `guard` is supposed to print a diagnostic and a traceback on the failure
        paths; letting that land in the suite's own output trains readers to
        scroll past tracebacks in CI logs, which is how a real one gets missed.
        """
        self._stderr = contextlib.redirect_stderr(io.StringIO())
        self._stderr.__enter__()
        self.addCleanup(self._stderr.__exit__, None, None, None)

    def test_rejection_passes_through(self) -> None:
        self.assertEqual(api.guard("check", False, lambda: api.EXIT_REJECTED),
                         api.EXIT_REJECTED)

    def test_clean_passes_through(self) -> None:
        self.assertEqual(api.guard("check", False, lambda: api.EXIT_OK), api.EXIT_OK)

    def test_unavailable_is_three_not_one(self) -> None:
        def body() -> int:
            raise api.ToolUnavailable("uel.lock is not readable JSON", code="UEL0003")

        self.assertEqual(api.guard("check", False, body), api.EXIT_UNAVAILABLE)

    def test_crash_is_three_not_one(self) -> None:
        """A kernel defect must not masquerade as an engineering verdict.

        An unhandled exception exits 1 through a shell, which under this
        contract means "the model was rejected" — so a caller would go rewrite
        correct physics to satisfy a bug.
        """
        def body() -> int:
            raise ZeroDivisionError("division by zero in a rollup")

        self.assertEqual(api.guard("check", False, body), api.EXIT_UNAVAILABLE)

    def test_unavailable_still_emits_a_parseable_envelope(self) -> None:
        """Under --json the contract promises stdout is always parseable —
        including on failure, which is exactly when a caller most needs to
        read the reason."""
        def body() -> int:
            raise api.ToolUnavailable("project root has no uel.toml", code="UEL0001")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = api.guard("check", True, body)
        self.assertEqual(rc, api.EXIT_UNAVAILABLE)
        parsed = json.loads(out.getvalue())
        self.assertFalse(parsed["uel"]["ok"])
        self.assertEqual(parsed["diagnostics"][0]["code"], "UEL0001")
        self.assertIn("fix the environment", parsed["diagnostics"][0]["reason"])

    def test_codes_are_distinct(self) -> None:
        self.assertEqual(
            len({api.EXIT_OK, api.EXIT_REJECTED, api.EXIT_USAGE, api.EXIT_UNAVAILABLE}), 4)

class TestExitForMapping(unittest.TestCase):
    def test_clean_is_zero(self) -> None:
        self.assertEqual(api.exit_for(Bag()), api.EXIT_OK)

    def test_pure_environment_failure_is_three(self) -> None:
        bag = Bag()
        bag.error("UEL0003", "uel.lock is not readable JSON")
        self.assertEqual(api.exit_for(bag), api.EXIT_UNAVAILABLE)

    def test_a_real_finding_alongside_an_environment_failure_is_one(self) -> None:
        """The conservative direction, and the one that matters.

        A caller that saw 3 and stopped reading diagnostics would walk past a
        genuine rejection. Mixed causes mean the graph *was* judged.
        """
        bag = Bag()
        bag.error("UEL0003", "uel.lock is not readable JSON")
        bag.error("UEL0403", "worst-case draw exceeds declared supply")
        self.assertEqual(api.exit_for(bag), api.EXIT_REJECTED)

    def test_warnings_never_change_the_code(self) -> None:
        bag = Bag()
        bag.warning("UEL0406", "an 'in' port is never connected")
        bag.info("UEL0405", "rollup has unvalued leaves")
        self.assertEqual(api.exit_for(bag), api.EXIT_OK)

class TestCliHonoursTheContract(unittest.TestCase):
    """End to end through `main()` — the shape a real caller actually sees."""

    EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "apache-one"

    def setUp(self) -> None:
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.project = self.td / "slice"
        shutil.copytree(self.EXAMPLE, self.project)

    def _run(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(list(argv))
        return rc, out.getvalue()

    def test_clean_project_exits_zero_with_an_ok_envelope(self) -> None:
        rc, out = self._run("check", str(self.project), "--json")
        self.assertEqual(rc, api.EXIT_OK)
        env = json.loads(out)
        self.assertTrue(env["uel"]["ok"])
        self.assertEqual(env["uel"]["protocol"], api.PROTOCOL)
        self.assertEqual(env["uel"]["command"], "check")
        self.assertGreater(env["result"]["nodes"], 0)

    def test_missing_project_is_three_not_one(self) -> None:
        rc, _ = self._run("check", str(self.td / "nowhere"))
        self.assertEqual(rc, api.EXIT_UNAVAILABLE,
                         "a project that cannot be read is an environment failure")

    def test_corrupt_lock_is_three_not_one(self) -> None:
        (self.project / "uel.lock").write_text("not json{", encoding="utf-8")
        rc, _ = self._run("check", str(self.project))
        self.assertEqual(rc, api.EXIT_UNAVAILABLE)

    def test_rejected_model_is_one(self) -> None:
        p = self.project / "model" / "structure.uel"
        p.write_text(p.read_text(encoding="utf-8").replace("budget mass <= 470 g",
                                                           "budget mass <= 470 W"),
                     encoding="utf-8")
        rc, _ = self._run("check", str(self.project))
        self.assertEqual(rc, api.EXIT_REJECTED,
                         "a dimension error is a judgment about the graph")

    def test_unknown_command_is_two(self) -> None:
        with self.assertRaises(SystemExit) as cm:  # argparse's own usage exit
            self._run("notacommand")
        self.assertEqual(cm.exception.code, api.EXIT_USAGE)

    def test_json_stdout_is_only_the_envelope(self) -> None:
        """The contract promises stdout can be piped into a parser
        unconditionally — nothing else may share it."""
        _, out = self._run("check", str(self.project), "--json")
        json.loads(out)  # raises if any chatter shares the stream

if __name__ == "__main__":
    unittest.main()
