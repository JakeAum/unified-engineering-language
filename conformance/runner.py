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
  economics/ ADR-0011 — attention ranking / information value → expected orderings

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
# Phase 2: parse / units / fmt / fixloop / check
# ---------------------------------------------------------------------------


def _expected_diags(path: Path) -> list[dict]:
    import json

    exp = path.with_suffix(".expect.json")
    if not exp.exists():
        return []
    return json.loads(exp.read_text(encoding="utf-8"))


def _match_diags(expected: list[dict], got: list) -> tuple[bool, str]:
    """Match on (code, line?) multisets; expected line omitted = any line."""
    got_pairs = [(d.code, d.span.line, d.severity) for d in got]
    remaining = list(got_pairs)
    for e in expected:
        code, line = e["code"], e.get("line")
        hit = next(
            (g for g in remaining if g[0] == code and (line is None or g[1] == line)),
            None,
        )
        if hit is None:
            return False, f"expected {code}" + (f" at line {line}" if line else "") + \
                f"; got {sorted(set((c, l) for c, l, _ in got_pairs))}"
        remaining.remove(hit)
    extra_errors = [g for g in remaining if g[2] == "error"]
    if extra_errors:
        return False, f"unexpected errors: {sorted(set((c, l) for c, l, _ in extra_errors))}"
    return True, f"{len(expected)} expected diagnostics matched, no unexpected errors"


@handler("parse", "*.uel")
def run_parse_case(path: Path) -> tuple[bool, str]:
    from uel.diagnostics import Bag
    from uel.parser import parse_text

    bag = Bag()
    parse_text(path.read_text(encoding="utf-8"), path.name, bag)
    return _match_diags(_expected_diags(path), bag.sorted())


@handler("units", "*.uel")
def run_units_case(path: Path) -> tuple[bool, str]:
    """Single file resolved against the stdlib (full name/unit resolution)."""
    import shutil
    import tempfile

    from uel.diagnostics import Bag
    from uel.project import load_project
    from uel.resolver import resolve_project

    with tempfile.TemporaryDirectory() as td:
        proj = Path(td)
        shutil.copy(path, proj / path.name)
        bag = Bag()
        project = load_project(proj, bag)
        if not bag.errors:
            resolve_project(project, bag)
        # rewrite temp-dir file names for stable matching
        for d in bag.items:
            if d.span.file.endswith(path.name):
                d.span.file = path.name
        return _match_diags(_expected_diags(path), bag.sorted())


@handler("fmt", "*.uel")
def run_fmt_case(path: Path) -> tuple[bool, str]:
    from uel.diagnostics import Bag
    from uel.formatter import format_ast
    from uel.parser import parse_text
    from uel.uast import fingerprint

    src = path.read_text(encoding="utf-8")
    bag = Bag()
    ast = parse_text(src, path.name, bag)
    if bag.errors:
        return False, "fmt case must parse cleanly: " + bag.render({path.name: src}).splitlines()[0]
    once = format_ast(ast)
    bag2 = Bag()
    ast2 = parse_text(once, path.name, bag2)
    if bag2.errors:
        return False, "formatted output no longer parses"
    if fingerprint(ast2) != fingerprint(ast):
        return False, "formatting changed the AST fingerprint (meaning not preserved)"
    twice = format_ast(ast2)
    if once != twice:
        return False, "formatter is not idempotent"
    golden = path.with_suffix(".golden")
    if golden.exists():
        want = golden.read_text(encoding="utf-8")
        if once != want:
            return False, "formatted output differs from golden file"
    return True, "idempotent, AST-preserving" + (", matches golden" if golden.exists() else "")


@handler("fixloop", "*")
def run_fixloop_case(path: Path) -> tuple[bool, str]:
    """Seeded-error project converges to clean under the mechanical fix driver."""
    import shutil
    import tempfile

    from .fixdriver import run_loop

    if not path.is_dir():
        return True, "skipped (not a case dir)"
    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / path.name
        shutil.copytree(path, work)
        ok, log = run_loop(work, max_rounds=6, verbose=False)
        return ok, "; ".join(log)


@handler("derisk", "*")
def run_derisk_case(path: Path) -> tuple[bool, str]:
    """R1 de-risk pair set (program §8.1, spec §10.1): ten real cross-domain
    analysis pairs encoded in the draft envelope formalism; each must produce
    the physically right verdict. Same mechanics as `check` cases."""
    return run_check_case(path)


@handler("check", "*")
def run_check_case(path: Path) -> tuple[bool, str]:
    """Full-project check against expected diagnostics (expected.json)."""
    import json

    from uel.checker import run_checks
    from uel.diagnostics import Bag
    from uel.project import load_project
    from uel.resolver import resolve_project

    if not path.is_dir():
        return True, "skipped (not a case dir)"
    expected = json.loads((path / "expected.json").read_text(encoding="utf-8")) \
        if (path / "expected.json").exists() else []
    bag = Bag()
    project = load_project(path, bag)
    if not bag.errors:
        res = resolve_project(project, bag)
        run_checks(res, bag, lock=False)
    return _match_diags(expected, bag.sorted())


@handler("economics", "*")
def run_economics_case(path: Path) -> tuple[bool, str]:
    """ADR-0011 attention/info-value machinery, graded against expected orderings.

    expected.json may assert any of: "rank" (exact value-order), "include_fresh"
    (widen the ranked set past the stale frontier), "scores" and "terms"
    (node -> expected score / normalized term values), "frontier" (node ->
    buildable-now flag), "measure_top" and "measure_order" (the highest-value
    candidate measurements, in order), "measure_fields" (target -> expected
    field values), and "advisories" (UEL09xx codes that must be raised).

    Cases carry no lock, so every executable is 'missing' and every number is
    reproducible without running a core: what is pinned is the *semantics* of
    the ranking, which must survive a weight amendment or fail loudly.
    """
    import json

    from uel import economics as E
    from uel.checker import run_checks
    from uel.diagnostics import Bag
    from uel.lockfile import Lock
    from uel.project import load_project
    from uel.resolver import resolve_project
    from uel.staleness import compute

    if not path.is_dir():
        return True, "skipped (not a case dir)"
    expected = json.loads((path / "expected.json").read_text(encoding="utf-8"))
    bag = Bag()
    project = load_project(path, bag)
    res = resolve_project(project, bag) if not bag.errors else None
    if res is None or bag.errors:
        return False, "economics case must resolve cleanly: " + \
            "; ".join(f"{d.code} {d.message}" for d in bag.sorted()[:3])
    rollups = run_checks(res, Bag(), lock=False) or {}
    lock = Lock.load(project.lock_path)
    rep = compute(res, lock)
    sig = E.signals(res, rep, lock, rollups)
    ranked = E.rank(res, rep, lock, sig=sig, include_fresh=expected.get("include_fresh", False))
    values = E.info_value(res, rep, lock, sig=sig)
    abag = Bag()
    E.advise(sig, ranked, values, abag)

    checked: list[str] = []
    got = [r.name for r in ranked]
    if (want := expected.get("rank")) is not None:
        if got != want:
            return False, f"rank: expected {want}, got {got}"
        checked.append(f"rank order exact ({len(got)} nodes)")
    by = {r.name: r for r in ranked}
    for name, want_score in sorted(expected.get("scores", {}).items()):
        if name not in by:
            return False, f"scores: '{name}' is not in the ranked set {got}"
        if abs(by[name].score - want_score) > 1e-6:
            return False, f"scores: '{name}' expected {want_score}, got {by[name].score}"
    for name, want_terms in sorted(expected.get("terms", {}).items()):
        if name not in by:
            return False, f"terms: '{name}' is not in the ranked set {got}"
        have = {t.name: t.value for t in by[name].terms}
        for tname, tval in sorted(want_terms.items()):
            if abs(have.get(tname, 0.0) - tval) > 1e-6:
                return False, (f"terms: '{name}.{tname}' expected {tval}, "
                               f"got {have.get(tname, 0.0)}")
    if expected.get("scores") or expected.get("terms"):
        checked.append(f"{len(expected.get('scores', {})) + len(expected.get('terms', {}))} "
                       "score/term assertions")
    for name, want_flag in sorted(expected.get("frontier", {}).items()):
        if name not in by:
            return False, f"frontier: '{name}' is not in the ranked set {got}"
        if by[name].frontier != want_flag:
            return False, f"frontier: '{name}' expected {want_flag}, got {by[name].frontier}"
    if expected.get("frontier"):
        checked.append(f"{len(expected['frontier'])} frontier flags")
    got_m = [m.target for m in values]
    if "measure_top" in expected:  # null asserts that nothing is measurable
        want_top = expected["measure_top"]
        if (got_m[0] if got_m else None) != want_top:
            return False, f"measure_top: expected {want_top!r}, got {got_m[:3]}"
        checked.append("top measurement" if want_top else "no measurable ignorance")
    if (want_m := expected.get("measure_order")) is not None:
        if got_m[:len(want_m)] != want_m:
            return False, f"measure_order: expected {want_m}, got {got_m[:len(want_m) + 1]}"
        checked.append(f"measurement order ({len(want_m)})")
    mby = {m.target: m for m in values}
    for target, fields in sorted(expected.get("measure_fields", {}).items()):
        if target not in mby:
            return False, f"measure_fields: '{target}' is not a candidate; have {got_m[:5]}"
        for f, want_v in sorted(fields.items()):
            have_v = getattr(mby[target], f, None)
            if isinstance(want_v, (int, float)) and isinstance(have_v, (int, float)):
                if abs(have_v - want_v) > 1e-6:
                    return False, f"measure_fields: '{target}.{f}' expected {want_v}, got {have_v}"
            elif have_v != want_v:
                return False, f"measure_fields: '{target}.{f}' expected {want_v!r}, got {have_v!r}"
        checked.append(f"{target} fields")
    if (want_codes := expected.get("advisories")) is not None:
        got_codes = sorted({d.code for d in abag.items})
        if sorted(set(want_codes)) != got_codes:
            return False, f"advisories: expected {sorted(set(want_codes))}, got {got_codes}"
        checked.append(f"advisories {got_codes}")
    return True, ", ".join(checked) or "nothing asserted"


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
