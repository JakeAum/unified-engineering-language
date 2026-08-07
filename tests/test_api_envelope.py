"""The machine-facing door: envelope shape and exit-code discipline.

These cases exist to keep two promises that a machine caller cannot verify for
itself: that stdout under `--json` is always exactly one parseable envelope, and
that "your model is wrong" (1) is never confused with "I could not run" (3).
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from uel import api
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

if __name__ == "__main__":
    unittest.main()
