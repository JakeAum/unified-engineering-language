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
        if only and name not in only: continue
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
        if entry.status == "fresh" and any(v.kind in ("monotone", "case") for v in an.verifies):
            run_verify_probes(res, an, name, entry, lock, bag)
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

def _assemble_payload(res: Resolution, an: G.Analysis, name: str, lock: Lock,
                      bag: Bag, sp: Span) -> dict | None:
    """The core-protocol stdin object: static values from the graph, upstream
    outputs from the lock. Shared by the main run and verification probes."""
    inputs: dict[str, dict] = {}
    for local in sorted(an.knowns):
        rr = res.known_refs.get((name, local))
        if rr is None:
            bag.error("UEL0703", f"{name}: known '{local}' is unresolved at run time", sp)
            return None
        if rr.kind == "output":
            producer = lock.nodes.get(rr.node)
            out_name = rr.target.rsplit(".", 1)[1]
            out = producer.outputs.get(out_name) if producer else None
            if out is None:
                bag.error("UEL0703", f"{name}: upstream output '{rr.target}' has never been produced", sp)
                return None
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
    return {
        "node": name,
        "kind": an.akind,
        "seed": PINNED_SEED,
        "inputs": inputs,
        "params": {k: _payload_quantity(q) for k, q in sorted(an.params.items())},
        "outputs_declared": {k: {"unit": o.unit, "artifact": o.artifact}
                             for k, o in sorted(an.outputs.items())},
    }

def _invoke(root, core_path: str, payload: dict) -> tuple[dict | None, str]:
    """Run a python core once; return (stdout object, error text)."""
    cmd = [sys.executable, str(root / core_path)]
    try:
        proc = subprocess.run(
            cmd, input=json.dumps(payload).encode("utf-8"),
            capture_output=True, timeout=CORE_TIMEOUT_S, cwd=root,
        )
    except subprocess.TimeoutExpired:
        return None, f"core timed out after {CORE_TIMEOUT_S}s ({core_path})"
    except OSError as e:
        return None, f"cannot execute core: {e}"
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        return None, f"core exited {proc.returncode}: " + ("; ".join(tail) or "no stderr")
    try:
        obj = json.loads(proc.stdout.decode("utf-8"))
        assert isinstance(obj, dict)
        return obj, ""
    except (ValueError, AssertionError):
        return None, "core did not emit a JSON object on stdout"

def _run_core(res: Resolution, an: G.Analysis, name: str, lock: Lock, bag: Bag) -> LockEntry:
    sp = _node_span(res, name)
    entry = LockEntry(status="failed")
    pol = res.project.tolerances
    root = res.project.root

    payload = _assemble_payload(res, an, name, lock, bag, sp)
    if payload is None: return entry

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

# expr/stub cores: kernel-evaluated (v0.2, ADR-0005)

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
    if not isinstance(value, (int, float)) or isinstance(value, bool): return None
    si = u.to_si(float(value))
    half = 0.0
    if unc and isinstance(unc.get("value"), (int, float)):
        if unc.get("kind") == "abs":
            half = abs(float(unc["value"])) * u.factor
        elif unc.get("kind") == "rel":
            half = abs(float(value)) * abs(float(unc["value"])) * u.factor
    return (si - half, si, si + half)

def _expr_ivs(res: Resolution, an: G.Analysis, name: str, lock: Lock,
              bag: Bag, sp: Span) -> dict[str, X.IV] | None:
    """Canonical-SI interval inputs for an expr/stub core. Shared by the main
    run and verification probes."""
    ivs: dict[str, X.IV] = {}
    for local in sorted(an.knowns):
        rr = res.known_refs.get((name, local))
        if rr is None:
            bag.error("UEL0703", f"{name}: known '{local}' is unresolved at run time", sp)
            return None
        if rr.kind == "output":
            producer = lock.nodes.get(rr.node)
            out_name = rr.target.rsplit(".", 1)[1]
            out = producer.outputs.get(out_name) if producer else None
            if out is None:
                bag.error("UEL0703", f"{name}: upstream output '{rr.target}' has never been produced", sp)
                return None
            iv = _si_iv(out.value, out.unit, out.unc if isinstance(out.unc, dict) else None)
        else:
            assert rr.quantity is not None
            q = rr.quantity
            iv = _si_iv(list(q.value) if isinstance(q.value, tuple) else q.value,
                        q.unit, q.unc.to_obj())
        if iv is None:
            bag.error("UEL0703", f"{name}: known '{local}' has no numeric value to evaluate", sp)
            return None
        ivs[local] = iv
    for pname, q in sorted(an.params.items()):
        iv = _si_iv(list(q.value) if isinstance(q.value, tuple) else q.value, q.unit, q.unc.to_obj())
        if iv is None:
            bag.error("UEL0703", f"{name}: param '{pname}' has no numeric value to evaluate", sp)
            return None
        ivs[pname] = iv
    return ivs

def _run_expr_core(res: Resolution, an: G.Analysis, name: str, lock: Lock, bag: Bag) -> LockEntry:
    sp = _node_span(res, name)
    entry = LockEntry(status="failed")
    pol = res.project.tolerances
    prog = res.expr_programs.get(name)
    if prog is None:
        bag.error("UEL0703", f"{name}: {an.core.lang} core has no parsed body "
                  "(graph loaded without sources?)", sp)
        return entry

    ivs = _expr_ivs(res, an, name, lock, bag, sp)
    if ivs is None: return entry

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

# ---------------------------------------------------------------------------
# Verification probes (v0.3, ADR-0008): monotone + golden-case contracts,
# executed right after a successful run; the evidence lives in the lock.
# ---------------------------------------------------------------------------

def _out_si(value, unit_text: str) -> float | None:
    try:
        u = parse_unit(unit_text)
    except UnitError:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool): return u.to_si(float(value))
    return None

def _rerun_outputs(res: Resolution, an: G.Analysis, name: str, lock: Lock, bag: Bag,
                   sp: Span, overrides: dict[str, float]) -> tuple[dict[str, float] | None, str]:
    """Re-execute a core with SI-value input overrides; return {output: si}."""
    if an.core.lang in ("expr", "stub"):
        prog = res.expr_programs.get(name)
        ivs = _expr_ivs(res, an, name, lock, bag, sp)
        if prog is None or ivs is None: return None, "inputs unavailable for probe"
        for k, si in overrides.items():
            ivs[k] = (si, si, si)
        try:
            outs = X.evaluate_program(prog, ivs, list(an.outputs))
        except X.ExprEvalError as e:
            return None, f"probe evaluation failed at '{e.target}': {e}"
        return {o: iv[1] for o, iv in outs.items()}, ""
    payload = _assemble_payload(res, an, name, lock, bag, sp)
    if payload is None: return None, "inputs unavailable for probe"
    for k, si in overrides.items():
        slot = payload["inputs"].get(k) if k in payload["inputs"] else payload["params"].get(k)
        if slot is None: return None, f"probe input '{k}' is not an input of this core"
        slot["si"] = si
        try:
            u = parse_unit(str(slot.get("unit", "")))
            if isinstance(slot.get("value"), (int, float)):
                slot["value"] = u.from_si(si)
        except UnitError:
            pass
    obj, err = _invoke(res.project.root, an.core.path, payload)
    if obj is None: return None, err
    outs: dict[str, float] = {}
    for oname, got in (obj.get("outputs", {}) or {}).items():
        if isinstance(got, dict) and isinstance(got.get("value"), (int, float)):
            si = _out_si(got["value"], str(got.get("unit", "")))
            if si is not None:
                outs[oname] = si
    return outs, ""

def _current_input_si(res: Resolution, an: G.Analysis, name: str, lock: Lock, key: str) -> float | None:
    rr = res.known_refs.get((name, key))
    if rr is not None:
        if rr.kind == "output":
            producer = lock.nodes.get(rr.node)
            out = producer.outputs.get(rr.target.rsplit(".", 1)[1]) if producer else None
            return _out_si(out.value, out.unit) if out else None
        q = rr.quantity
    else:
        q = an.params.get(key)
    if q is None or q.value is None: return None
    v = q.value
    if isinstance(v, tuple):
        v = (v[0] + v[1]) / 2.0
    return _out_si(float(v), q.unit)

def run_verify_probes(res: Resolution, an: G.Analysis, name: str, entry: LockEntry,
                      lock: Lock, bag: Bag) -> None:
    sp = _node_span(res, name)
    records: list[dict] = []
    for v in an.verifies:
        if v.kind == "monotone":
            rec = _probe_monotone(res, an, name, entry, lock, bag, sp, v)
        elif v.kind == "case":
            rec = _probe_case(res, an, name, lock, bag, sp, v)
        else:
            continue  # 'against' is a lock-vs-lock comparison, judged at check time
        records.append(rec)
        if not rec["ok"]:
            entry.status = "failed"
            bag.error(
                "UEL0808", f"{name}: {rec['contract']} FAILED — {rec['detail']}", sp,
                reason="a verification contract is the declared reason to believe this core "
                       "(ADR-0008); a run that breaks its own contract is not a result",
            )
    if records:
        entry.run["verify"] = records

def _probe_monotone(res, an, name, entry, lock, bag, sp, v: G.Verify) -> dict:
    contract = f"verify {v.output} monotone with {v.known} {v.direction}"
    base_out = entry.outputs.get(v.output)
    base_si = _out_si(base_out.value, base_out.unit) if base_out else None
    in_si = _current_input_si(res, an, name, lock, v.known)
    if base_si is None or in_si is None:
        return {"contract": contract, "ok": False, "detail": "baseline value unavailable for probe"}
    delta = 0.05 * abs(in_si) if in_si != 0.0 else 1.0
    outs, err = _rerun_outputs(res, an, name, lock, bag, sp, {v.known: in_si + delta})
    if outs is None or v.output not in outs:
        return {"contract": contract, "ok": False, "detail": err or "probe produced no output"}
    probed = outs[v.output]
    eps = 1e-9 * max(1.0, abs(base_si))
    ok = probed >= base_si - eps if v.direction == "rising" else probed <= base_si + eps
    detail = (f"{v.known} +{delta:g} (SI) moved {v.output} {base_si:g} -> {probed:g} (SI); "
              f"declared {v.direction}")
    return {"contract": contract, "ok": ok, "detail": detail}

def _probe_case(res, an, name, lock, bag, sp, v: G.Verify) -> dict:
    contract = f'verify case "{v.path}"'
    p = res.project.root / v.path
    try:
        case = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"contract": contract, "ok": False, "detail": f"cannot read case file: {e}"}
    overrides: dict[str, float] = {}
    for k, spec in (case.get("inputs", {}) or {}).items():
        try:
            u = parse_unit(str(spec.get("unit", "")))
            overrides[k] = u.to_si(float(spec["value"]))
        except (UnitError, KeyError, TypeError, ValueError):
            return {"contract": contract, "ok": False, "detail": f"malformed case input '{k}'"}
    outs, err = _rerun_outputs(res, an, name, lock, bag, sp, overrides)
    if outs is None: return {"contract": contract, "ok": False, "detail": err}
    misses: list[str] = []
    for oname, spec in (case.get("expect", {}) or {}).items():
        want = _out_si(spec.get("value"), str(spec.get("unit", ""))) if isinstance(spec, dict) else None
        got = outs.get(oname)
        if want is None or got is None:
            misses.append(f"{oname}: no comparable value")
            continue
        if v.tol_unit:
            try:
                tol_si = float(v.tol or 0.0) * parse_unit(v.tol_unit).factor
            except UnitError:
                tol_si = 0.0
            ok = abs(got - want) <= tol_si
        else:
            ok = abs(got - want) <= float(v.tol or 0.0) * max(abs(want), 1e-30)
        if not ok:
            misses.append(f"{oname}: got {got:g}, expected {want:g} (SI)")
    if misses: return {"contract": contract, "ok": False, "detail": "; ".join(misses)}
    n = len(case.get("expect", {}) or {})
    return {"contract": contract, "ok": True, "detail": f"{n} expected output(s) reproduced"}
