"""Model runtime: the local scheduler (spec §4.4).

Walks the stale set in dependency order and re-executes cores. Python cores run
through the JSON core protocol (docs/core-protocol.md); expr/stub cores (v0.2,
ADR-0005) are evaluated by the kernel itself — interval arithmetic over the
knowns' declared bands, no subprocess, with the canonical body as content.
Compile time gates runtime: nothing runs while the checker reports errors.
Early cutoff is re-evaluated *after* each upstream completes — an upstream
re-run that lands within tolerance leaves its consumers fresh, and they are
skipped.

Geometry nodes (spec §6.2) must return topological assertions; a geometry core
that returns none fails the build (UEL0601), and any failed assertion is a
compile-visible error (UEL0602), because a silently wrong part is the failure
mode this exists to kill.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field

from . import expr as X
from . import graph as G
from .diagnostics import Bag, Span
from .hashing import output_value_hash, sha, tool_pins
from .lockfile import Lock, LockEntry, LockOutput
from .resolver import Resolution
from .staleness import compute, executable_nodes
from .units import UnitError, parse_unit

CORE_TIMEOUT_S = 300
PINNED_SEED = 0  # spec §4.3 draft rule: solver nondeterminism handled by pinned seeds


@dataclass
class BuildResult:
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.failed


def _payload_quantity(q: G.Quantity) -> dict:
    o: dict = {}
    if q.value is not None:
        o["value"] = list(q.value) if isinstance(q.value, tuple) else q.value
    o["unit"] = q.unit
    try:
        u = parse_unit(q.unit)
        if q.value is not None:
            o["si"] = [u.to_si(v) for v in q.value] if isinstance(q.value, tuple) else u.to_si(q.value)
    except UnitError:
        pass
    if q.unc.kind != "none":
        o["unc"] = {"kind": q.unc.kind, **({"value": q.unc.value} if q.unc.value is not None else {})}
    return o


def _node_span(res: Resolution, name: str) -> Span:
    node = res.doc.nodes.get(name)
    src = getattr(node, "src", "")
    f, _, ln = src.partition(":")
    return Span(f, int(ln) if ln.isdigit() else 0)


def build(res: Resolution, bag: Bag, only: list[str] | None = None,
          dry_run: bool = False, verbose: bool = True) -> BuildResult:
    result = BuildResult()
    if bag.gates_runtime():
        bag.info("UEL0701", "build refused: compile-time errors present (compile time gates runtime, spec §4.4)")
        return result

    lock = Lock.load(res.project.lock_path, bag)
    lock.edition = res.doc.edition
    lock.tools = tool_pins()
    execs = executable_nodes(res.doc)
    pol = res.project.tolerances
    root = res.project.root

    rep = compute(res, lock)
    for name in rep.order:
        if only and name not in only:
            continue
        # recompute against the *current* lock: upstream runs may have restored freshness
        current = compute(res, lock).states[name]
        if current.status == "fresh":
            result.skipped.append(name)
            continue
        an = execs[name]
        if dry_run:
            result.ran.append(name)
            continue
        if verbose:
            what = an.core.path or f"{an.core.lang} core"
            print(f"build: running {name} ({what}) — {'; '.join(current.reasons)}")
        if an.core.lang in ("expr", "stub"):
            entry = _run_expr_core(res, an, name, lock, bag)
        else:
            entry = _run_core(res, an, name, lock, bag)
        entry.recipe = current.recipe
        entry.parts = current.parts
        lock.nodes[name] = entry
        if entry.status == "failed":
            result.failed.append(name)
        else:
            result.ran.append(name)
    if not dry_run:
        lock.save(res.project.lock_path)
    return result


def _run_core(res: Resolution, an: G.Analysis, name: str, lock: Lock, bag: Bag) -> LockEntry:
    sp = _node_span(res, name)
    entry = LockEntry(status="failed")
    pol = res.project.tolerances
    root = res.project.root

    # assemble inputs: static values from the graph, upstream outputs from the lock
    inputs: dict[str, dict] = {}
    for local in sorted(an.knowns):
        rr = res.known_refs.get((name, local))
        if rr is None:
            bag.error("UEL0703", f"{name}: known '{local}' is unresolved at run time", sp)
            return entry
        if rr.kind == "output":
            producer = lock.nodes.get(rr.node)
            out_name = rr.target.rsplit(".", 1)[1]
            out = producer.outputs.get(out_name) if producer else None
            if out is None:
                bag.error("UEL0703", f"{name}: upstream output '{rr.target}' has never been produced", sp)
                return entry
            inputs[local] = {"value": out.value, "unit": out.unit, **({"unc": out.unc} if out.unc else {})}
            try:
                u = parse_unit(out.unit)
                if isinstance(out.value, (int, float)):
                    inputs[local]["si"] = u.to_si(float(out.value))
                elif isinstance(out.value, list) and len(out.value) == 2:
                    inputs[local]["si"] = [u.to_si(float(v)) for v in out.value]
            except UnitError:
                pass
        else:
            assert rr.quantity is not None
            inputs[local] = _payload_quantity(rr.quantity)

    payload = {
        "node": name,
        "kind": an.akind,
        "seed": PINNED_SEED,
        "inputs": inputs,
        "params": {k: _payload_quantity(q) for k, q in sorted(an.params.items())},
        "outputs_declared": {k: {"unit": o.unit, "artifact": o.artifact}
                             for k, o in sorted(an.outputs.items())},
    }

    cmd = [sys.executable, str(root / an.core.path)]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, input=json.dumps(payload).encode("utf-8"),
            capture_output=True, timeout=CORE_TIMEOUT_S, cwd=root,
        )
    except subprocess.TimeoutExpired:
        bag.error("UEL0703", f"{name}: core timed out after {CORE_TIMEOUT_S}s ({an.core.path})", sp)
        return entry
    except OSError as e:
        bag.error("UEL0703", f"{name}: cannot execute core: {e}", sp)
        return entry
    wall = time.monotonic() - t0

    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        bag.error("UEL0703", f"{name}: core exited {proc.returncode} ({an.core.path})", sp,
                  reason="\n".join(tail) or "no stderr")
        return entry
    try:
        out_obj = json.loads(proc.stdout.decode("utf-8"))
        assert isinstance(out_obj, dict)
    except (ValueError, AssertionError):
        bag.error("UEL0703", f"{name}: core did not emit a JSON object on stdout ({an.core.path})", sp,
                  reason="the core protocol is JSON in on stdin, JSON out on stdout (docs/core-protocol.md)")
        return entry

    # validate outputs against declarations
    produced = out_obj.get("outputs", {}) or {}
    ok = True
    for oname, decl in an.outputs.items():
        if decl.artifact:
            art = produced.get(oname)
            if not isinstance(art, dict) or "artifact" not in art:
                bag.error("UEL0704", f"{name}: declared artifact output '{oname}' missing "
                          f"(expected {{\"artifact\": \"path\"}})", sp)
                ok = False
                continue
            apath = root / str(art["artifact"])
            try:
                h = sha(apath.read_bytes())
            except OSError:
                bag.error("UEL0704", f"{name}: artifact '{oname}' path '{art['artifact']}' unreadable", sp)
                ok = False
                continue
            entry.outputs[oname] = LockOutput(str(art["artifact"]), "", None, h, artifact=True)
            continue
        got = produced.get(oname)
        if not isinstance(got, dict) or "value" not in got:
            bag.error("UEL0704", f"{name}: core did not produce declared output '{oname}'", sp,
                      reason="outputs are typed, unit-carrying quantities (spec §3.2)")
            ok = False
            continue
        gunit = str(got.get("unit", ""))
        try:
            gu = parse_unit(gunit)
            du = parse_unit(decl.unit)
        except UnitError as e:
            bag.error("UEL0704", f"{name}: output '{oname}' unit problem: {e}", sp)
            ok = False
            continue
        if gu.dim != du.dim:
            bag.error("UEL0704",
                      f"{name}: output '{oname}' has unit '{gunit}', but is declared '{decl.unit or 'dimensionless'}'",
                      sp)
            ok = False
            continue
        raw = got["value"]
        # normalize into the declared unit for lock stability
        def conv(v: float) -> float:
            return du.from_si(gu.to_si(float(v)))
        import math as _math

        def finite(v: object) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool) and _math.isfinite(float(v))
        if isinstance(raw, list) and len(raw) == 2 and all(finite(v) for v in raw):
            value: object = [conv(raw[0]), conv(raw[1])]
        elif finite(raw):
            value = conv(raw)
        else:
            bag.error("UEL0704", f"{name}: output '{oname}' must be a finite number or [lo, hi] "
                      f"(got {raw!r})", sp,
                      reason="NaN/Inf are not representable in the graph; a diverged solve is a failed run, not a value")
            ok = False
            continue
        unc = got.get("unc") if isinstance(got.get("unc"), dict) else None
        entry.outputs[oname] = LockOutput(
            value, decl.unit, unc, output_value_hash(value, decl.unit, unc, pol)
        )

    for extra in sorted(set(produced) - set(an.outputs)):
        bag.warning("UEL0704", f"{name}: core produced undeclared output '{extra}' (ignored)", sp,
                    reason="declare it in `outputs {{ }}` to make it consumable; undeclared values cannot carry staleness")

    # geometry: features + mandatory topological assertions (spec §6.2)
    feats = out_obj.get("features", {}) or {}
    for fname, fv in sorted(feats.items()):
        if isinstance(fv, dict) and isinstance(fv.get("value"), (int, float)):
            entry.features[fname] = {"value": fv["value"], "unit": str(fv.get("unit", ""))}
    asserts = out_obj.get("assertions", []) or []
    entry.assertions = [
        {"name": str(a.get("name", f"assertion_{i}")), "passed": bool(a.get("passed")),
         **({"detail": str(a["detail"])} if a.get("detail") else {})}
        for i, a in enumerate(asserts) if isinstance(a, dict)
    ]
    if an.akind == "geometry":
        if not entry.assertions:
            bag.error("UEL0601", f"{name}: geometry core returned no topological assertions", sp,
                      reason="topological assertions are mandatory envelope elements of geometry (spec §6.2): a regeneration that silently grabs different topology must fail loudly, not make a wrong part")
            ok = False
        for a in entry.assertions:
            if not a["passed"]:
                bag.error("UEL0602", f"{name}: topological assertion '{a['name']}' failed"
                          + (f": {a.get('detail')}" if a.get("detail") else ""), sp)
                ok = False

    entry.status = "fresh" if ok else "failed"
    entry.run = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wall_s": round(wall, 3),
        "tools": tool_pins(),
        "seed": PINNED_SEED,
    }
    return entry


# ---------------------------------------------------------------------------
# expr/stub cores: kernel-evaluated (v0.2, ADR-0005)
# ---------------------------------------------------------------------------


def _si_iv(value, unit_text: str, unc: dict | None) -> X.IV | None:
    """A value + declared band → a canonical-SI (lo, nominal, hi) triple.

    Absolute uncertainty is a delta (scales by the unit factor, never picks up
    affine/level offsets); relative uncertainty is a fraction of the surface
    value, which for levels means a fraction of the dB figure."""
    try:
        u = parse_unit(unit_text)
    except UnitError:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        lo, hi = u.to_si(float(value[0])), u.to_si(float(value[1]))
        return (min(lo, hi), (lo + hi) / 2.0, max(lo, hi))
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    si = u.to_si(float(value))
    half = 0.0
    if unc and isinstance(unc.get("value"), (int, float)):
        if unc.get("kind") == "abs":
            half = abs(float(unc["value"])) * u.factor
        elif unc.get("kind") == "rel":
            half = abs(float(value)) * abs(float(unc["value"])) * u.factor
    return (si - half, si, si + half)


def _run_expr_core(res: Resolution, an: G.Analysis, name: str, lock: Lock, bag: Bag) -> LockEntry:
    sp = _node_span(res, name)
    entry = LockEntry(status="failed")
    pol = res.project.tolerances
    prog = res.expr_programs.get(name)
    if prog is None:
        bag.error("UEL0703", f"{name}: {an.core.lang} core has no parsed body "
                  "(graph loaded without sources?)", sp)
        return entry

    ivs: dict[str, X.IV] = {}
    for local in sorted(an.knowns):
        rr = res.known_refs.get((name, local))
        if rr is None:
            bag.error("UEL0703", f"{name}: known '{local}' is unresolved at run time", sp)
            return entry
        if rr.kind == "output":
            producer = lock.nodes.get(rr.node)
            out_name = rr.target.rsplit(".", 1)[1]
            out = producer.outputs.get(out_name) if producer else None
            if out is None:
                bag.error("UEL0703", f"{name}: upstream output '{rr.target}' has never been produced", sp)
                return entry
            iv = _si_iv(out.value, out.unit, out.unc if isinstance(out.unc, dict) else None)
        else:
            assert rr.quantity is not None
            q = rr.quantity
            iv = _si_iv(list(q.value) if isinstance(q.value, tuple) else q.value,
                        q.unit, q.unc.to_obj())
        if iv is None:
            bag.error("UEL0703", f"{name}: known '{local}' has no numeric value to evaluate", sp)
            return entry
        ivs[local] = iv
    for pname, q in sorted(an.params.items()):
        iv = _si_iv(list(q.value) if isinstance(q.value, tuple) else q.value, q.unit, q.unc.to_obj())
        if iv is None:
            bag.error("UEL0703", f"{name}: param '{pname}' has no numeric value to evaluate", sp)
            return entry
        ivs[pname] = iv

    t0 = time.monotonic()
    try:
        outs = X.evaluate_program(prog, ivs, list(an.outputs))
    except X.ExprEvalError as e:
        bag.error("UEL0703", f"{name}: expression for '{e.target}' failed: {e}", sp,
                  reason="a diverged formula is a failed run, not a value (spec §4.4)")
        return entry
    wall = time.monotonic() - t0

    def rnd(v: float) -> float:
        return float(f"{v:.6g}")

    for oname, decl in an.outputs.items():
        lo, nom, hi = outs[oname]
        try:
            u = parse_unit(decl.unit)
        except UnitError:
            bag.error("UEL0704", f"{name}: output '{oname}' has an invalid declared unit", sp)
            return entry
        half = max(nom - lo, hi - nom) / u.factor
        value = rnd(u.from_si(nom))
        unc = {"kind": "abs", "value": rnd(half)} if half > 1e-12 + abs(value) * 1e-9 else None
        entry.outputs[oname] = LockOutput(value, decl.unit, unc,
                                          output_value_hash(value, decl.unit, unc, pol))

    entry.status = "fresh"
    entry.run = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wall_s": round(wall, 6),
        "tools": tool_pins(),
        "seed": PINNED_SEED,
        "engine": an.core.lang,
    }
    return entry
