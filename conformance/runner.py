"""Conformance runner: discovers and executes cases under conformance/cases/.

Case kinds are registered per phase; each kind owns a directory:

  schema/    Phase 1 — canonical round-trip of graph documents (*.json)
  parse/     Phase 2 — surface syntax → expected diagnostics or clean parse
  units/     Phase 2 — dimension checking verdicts
  fmt/       Phase 2 — formatter idempotence + AST preservation
  fixloop/   Phase 2 — seeded errors whose diagnostics machine-apply to a clean fix
  check/     Phase 2+ — full-project check → expected diagnostic codes
  stale/     Phase 3 — edit scripts → expected stale sets
  build/     Phase 3 — scheduler runs → expected outputs within tolerance
  derisk/    Phase 4 — R1 envelope-formalism pair set (spec §10.1)

Exit code 0 iff every discovered case passes. Run: python -m conformance.runner
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

CASES = Path(__file__).resolve().parent / "cases"

# kind -> handler(case_path) -> (ok: bool, detail: str)
HANDLERS: dict = {}


def handler(kind: str, pattern: str = "*"):
    def deco(fn):
        HANDLERS[kind] = (fn, pattern)
        return fn

    return deco


# ---------------------------------------------------------------------------
# Phase 1: schema round-trip
# ---------------------------------------------------------------------------


@handler("schema", "*.json")
def run_schema_case(path: Path) -> tuple[bool, str]:
    import json

    from uel.graph import GraphDoc

    raw = json.loads(path.read_text(encoding="utf-8"))
    doc, errors = GraphDoc.from_obj(raw)
    if path.name.startswith("invalid_"):
        if errors:
            return True, f"rejected as expected ({len(errors)} schema errors)"
        return False, "invalid_* case was accepted but must be rejected"
    if errors:
        return False, "; ".join(str(e) for e in errors[:5])
    assert doc is not None
    once = doc.to_canonical()
    doc2, errors2 = GraphDoc.from_obj(json.loads(once.decode("utf-8")))
    if errors2 or doc2 is None:
        return False, "re-read of canonical form failed: " + "; ".join(str(e) for e in errors2[:5])
    twice = doc2.to_canonical()
    if once != twice:
        return False, "canonical encoding is not a fixpoint (decode∘encode changed bytes)"
    if doc2 != doc:
        return False, "semantic inequality after round-trip"
    return True, f"round-trip stable ({len(doc.nodes)} nodes)"


# ---------------------------------------------------------------------------
# Discovery and reporting
# ---------------------------------------------------------------------------


def discover(filter_: str | None) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for kind, (fn, pattern) in sorted(HANDLERS.items()):
        d = CASES / kind
        if not d.is_dir():
            continue
        for p in sorted(d.glob(pattern)):
            if p.name.startswith("_"):
                continue
            if filter_ and filter_ not in f"{kind}/{p.name}":
                continue
            found.append((kind, p))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="conformance.runner")
    ap.add_argument("-k", "--filter", default=None, help="substring filter on kind/name")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    cases = discover(args.filter)
    if not cases:
        print("conformance: no cases discovered", file=sys.stderr)
        return 1

    failures = 0
    by_kind: dict[str, list[int]] = {}
    for kind, path in cases:
        fn, _ = HANDLERS[kind]
        try:
            ok, detail = fn(path)
        except Exception:
            ok, detail = False, "handler raised:\n" + traceback.format_exc(limit=8)
        by_kind.setdefault(kind, [0, 0])[0 if ok else 1] += 1
        mark = "PASS" if ok else "FAIL"
        if not ok or not args.quiet:
            print(f"[{mark}] {kind}/{path.name}: {detail}")
        failures += 0 if ok else 1

    total = len(cases)
    summary = ", ".join(f"{k}: {v[0]}/{v[0] + v[1]}" for k, v in sorted(by_kind.items()))
    print(f"\nconformance: {total - failures}/{total} passed  ({summary})")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
