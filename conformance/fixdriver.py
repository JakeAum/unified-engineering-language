"""The fix-loop driver: proof that diagnostics are machine-actionable.

Simulates the dumbest possible agent: it reads `uel check --json`, applies every
`fix.replace` verbatim at `fix.span`, and re-checks — no model, no judgment. If
seeded errors converge to a clean check under this driver, the diagnostics carry
enough mechanical content for real agents to iterate against (program §4, Phase 2
exit criterion).

Usage: python -m conformance.fixdriver <project-dir> [--max-rounds N]
Exit 0 on convergence; prints a round-by-round account.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _check_json(root: Path) -> list[dict]:
    from uel.diagnostics import Bag
    from uel.project import load_project
    from uel.resolver import resolve_project
    from uel.checker import run_checks

    bag = Bag()
    project = load_project(root, bag)
    if not bag.errors:
        res = resolve_project(project, bag)
        run_checks(res, bag, lock=False)
    return [d.to_obj() for d in bag.sorted()]


def apply_fixes(root: Path, diags: list[dict]) -> int:
    """Apply every non-overlapping mechanical fix, most-specific spans first."""
    by_file: dict[str, list[tuple[int, int, int, str]]] = {}
    for d in diags:
        fix = d.get("fix")
        if not fix or fix.get("replace") is None:
            continue
        span = fix.get("span") or d.get("span") or {}
        f, line, col = span.get("file", ""), span.get("line", 0), span.get("col", 0)
        end_col = span.get("end_col", 0)
        if not f or not line or not col or f.startswith("<stdlib>"):
            continue
        by_file.setdefault(f, []).append((line, col, end_col or col + 1, fix["replace"]))

    applied = 0
    for rel, edits in by_file.items():
        p = root / rel
        if not p.is_file():
            continue
        lines = p.read_text(encoding="utf-8").split("\n")
        # right-to-left, bottom-to-top so spans stay valid; skip overlaps
        edits.sort(key=lambda e: (e[0], e[1]), reverse=True)
        occupied: dict[int, list[tuple[int, int]]] = {}
        for line, col, end_col, replacement in edits:
            if line < 1 or line > len(lines):
                continue
            if any(not (end_col <= a or col >= b) for a, b in occupied.get(line, [])):
                continue
            text = lines[line - 1]
            if col - 1 > len(text):
                continue
            lines[line - 1] = text[: col - 1] + replacement + text[end_col - 1:]
            occupied.setdefault(line, []).append((col, end_col))
            applied += 1
        p.write_text("\n".join(lines), encoding="utf-8")
    return applied


def run_loop(root: Path, max_rounds: int = 6, verbose: bool = True) -> tuple[bool, list[str]]:
    log: list[str] = []
    for round_no in range(1, max_rounds + 1):
        diags = _check_json(root)
        errors = [d for d in diags if d["severity"] == "error"]
        if not errors:
            log.append(f"round {round_no}: clean ({len(diags)} advisories)")
            return True, log
        applied = apply_fixes(root, diags)
        log.append(f"round {round_no}: {len(errors)} errors, {applied} mechanical fixes applied")
        if applied == 0:
            log.append("stuck: errors remain but no mechanical fixes were offered")
            return False, log
    log.append(f"did not converge within {max_rounds} rounds")
    return False, log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="conformance.fixdriver")
    ap.add_argument("project")
    ap.add_argument("--max-rounds", type=int, default=6)
    args = ap.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    ok, log = run_loop(Path(args.project), args.max_rounds)
    print("\n".join(log))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
