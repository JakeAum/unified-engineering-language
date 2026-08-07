"""The tool surface is an API — enforcement (docs/stability.md, Tier 1).

A stability contract graded by good intentions is not a contract. These are its
teeth.

The load-bearing property is **code identity**: `UEL0501` must mean on the last
day of the edition what it meant the day it was minted. Callers — hooks, CI,
MCP wrappers, and eventually models prompted against this surface — match on
`code` and are told explicitly never to match on message prose. That promise is
only worth something if breaking it fails a build.

Note what is deliberately *not* asserted here: message and reason text. Those
are Tier 3, free to be rewritten any time a diagnostic can teach better. The
split is the whole design — frozen identity, liquid explanation.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from uel.diagnostics import CODES, SEVERITIES

FROZEN = Path(__file__).parent / "frozen_code_registry.json"
CODE_RE = re.compile(r"^UEL\d{4}$")

class TestCodeRegistryAppendOnly(unittest.TestCase):
    """Tier 1: a code's identity is frozen; the code *set* is additive-only."""

    def setUp(self) -> None:
        self.frozen = json.loads(FROZEN.read_text())["codes"]

    def test_no_code_disappears(self) -> None:
        """Retired rules keep their registry entry.

        Locks, projections, and review dossiers are content-addressed and
        long-lived: a historical artifact citing UEL0403 must stay readable
        after the rule that minted it stops firing. A code is retired, never
        deleted — the way a tail number is never reissued.
        """
        missing = sorted(set(self.frozen) - set(CODES))
        self.assertEqual(
            missing, [],
            f"diagnostic code(s) removed from the registry: {missing}. "
            "Codes are never deleted (docs/stability.md, Tier 1) — mark the entry "
            "retired and leave it in place so historical artifacts stay readable.",
        )

    def test_no_code_changes_meaning(self) -> None:
        """A code's registered title is its identity. Rewording it silently
        re-points every caller that matched on it."""
        drifted = [
            (code, title, CODES[code])
            for code, title in sorted(self.frozen.items())
            if code in CODES and CODES[code] != title
        ]
        self.assertEqual(
            drifted, [],
            "diagnostic code title(s) changed: "
            + "; ".join(f"{c}: {was!r} -> {now!r}" for c, was, now in drifted)
            + ". A code means what it meant when it was minted (docs/stability.md, "
            "Tier 1). To say something new, mint a new code. To say the same thing "
            "better, edit the message and reason — those are Tier 3 and free.",
        )

    def test_additions_are_allowed(self) -> None:
        """The inverse guard: this suite must never ossify the registry.

        New codes are Tier 2 and explicitly permitted. This test documents that
        by asserting only that additions are well-formed, never that they are
        absent — so a contributor minting UEL0901 is not fighting the contract.
        """
        added = sorted(set(CODES) - set(self.frozen))
        for code in added:
            self.assertRegex(code, CODE_RE, f"new code {code!r} is malformed")
            self.assertTrue(CODES[code].strip(), f"new code {code} has an empty title")

class TestSurfaceInvariants(unittest.TestCase):
    def test_every_code_wellformed(self) -> None:
        for code, title in sorted(CODES.items()):
            self.assertRegex(code, CODE_RE, f"malformed diagnostic code {code!r}")
            self.assertTrue(title.strip(), f"{code} has an empty title")

    def test_severity_vocabulary_frozen(self) -> None:
        """Tier 1. Callers branch on severity; a fourth value silently changes
        what every existing consumer does with it."""
        self.assertEqual(SEVERITIES, ("error", "warning", "info"))

    def test_frozen_snapshot_is_a_subset_not_a_mirror(self) -> None:
        """Guard against the snapshot being regenerated to paper over a break.

        Refreshing the snapshot is legitimate *only* to record additions. If a
        refresh ever drops or rewords an entry, the two tests above stop being
        able to see it — so the snapshot's own protocol version is pinned, and
        changing it demands an edition bump and an ADR.
        """
        meta = json.loads(FROZEN.read_text())
        self.assertEqual(meta["protocol"], 1)
        self.assertLessEqual(set(meta["codes"]), set(CODES))

if __name__ == "__main__":
    unittest.main()
