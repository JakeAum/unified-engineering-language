"""Output targets and maturity accounting (v0.2, ADR-0007).

**Targets.** An output may declare the acceptance bound it exists to satisfy:

    outputs { margin_db : dB ± target >= req.LNK-002.min_margin_db }

After every build the locked value is compared against the bound — requirement
satisfaction becomes a computed property of the graph, not a sentence in a
judgment. A violated target is a compile-visible error (UEL0804); a target on a
never-built output is announced as pending (UEL0805, info). The comparison is
nominal-value against bound; when the declared band crosses the bound the
message says so, because "passing on the nominal, failing in the band" is
exactly the situation a reviewer needs handed to them.

**Maturity.** `core stub { … }` is the v0.1 ground-station org pattern —
executable placeholders that keep every consumer green from minute zero —
promoted into the language. Stubs run like expr cores, but each one is
announced (UEL0807, info) and counted in the status projection: a design that
is still standing on placeholders says so on every check.
"""

from __future__ import annotations

from . import graph as G
from .diagnostics import Bag, Span, span_of
from .lockfile import Lock
from .resolver import Resolution
from .units import UnitError, parse_unit

def _bound_si(res: Resolution, lock: Lock, node: str, out: str,
              od: G.OutputDecl) -> tuple[float | None, str, str]:
    """(bound in SI-canonical, display text, source description) for a target."""
    if od.target_value is not None:
        q = od.target_value
        if q.value is None or isinstance(q.value, tuple): return None, "", ""
        try:
            si = parse_unit(q.unit).to_si(float(q.value))
        except UnitError:
            return None, "", ""
        return si, f"{q.value:g} {q.unit}".strip(), "declared bound"
    rr = res.target_refs.get((node, out))
    if rr is None: return None, "", ""
    if rr.kind == "output":
        producer = lock.nodes.get(rr.node)
        oname = rr.target.rsplit(".", 1)[1]
        o = producer.outputs.get(oname) if producer else None
        if o is None or o.value is None or isinstance(o.value, list): return None, "", ""
        try:
            si = parse_unit(o.unit).to_si(float(o.value))
        except UnitError:
            return None, "", ""
        return si, f"{o.value:g} {o.unit}".strip(), f"from {rr.target}"
    q = rr.quantity
    if q is None or q.value is None or isinstance(q.value, tuple): return None, "", ""
    try:
        si = parse_unit(q.unit).to_si(float(q.value))
    except UnitError:
        return None, "", ""
    return si, f"{q.value:g} {q.unit}".strip(), f"from {rr.target}"

def _ref_si(res: Resolution, lock: Lock, node: str, idx: int) -> tuple[float | None, str]:
    """SI value + display text of a verify-against reference."""
    rr = res.verify_refs.get((node, idx))
    if rr is None: return None, ""
    if rr.kind == "output":
        producer = lock.nodes.get(rr.node)
        oname = rr.target.rsplit(".", 1)[1]
        o = producer.outputs.get(oname) if producer else None
        if o is None or o.value is None or isinstance(o.value, list): return None, ""
        try:
            return parse_unit(o.unit).to_si(float(o.value)), f"{o.value:g} {o.unit}".strip()
        except UnitError:
            return None, ""
    q = rr.quantity
    if q is None or q.value is None or isinstance(q.value, tuple): return None, ""
    try:
        return parse_unit(q.unit).to_si(float(q.value)), f"{q.value:g} {q.unit}".strip()
    except UnitError:
        return None, ""

def check(res: Resolution, bag: Bag, lock: Lock) -> None:
    analyses = res.doc.analyses()
    for name in sorted(analyses):
        an = analyses[name]
        sp = span_of(an)
        for out_name in sorted(an.outputs):
            od = an.outputs[out_name]
            if not od.target_op: continue
            bound_si, bound_txt, source = _bound_si(res, lock, name, out_name, od)
            if bound_si is None:
                continue  # unresolvable bound already diagnosed at resolution
            entry = lock.nodes.get(name)
            out = entry.outputs.get(out_name) if entry else None
            if out is None or out.value is None or isinstance(out.value, list):
                bag.info(
                    "UEL0805",
                    f"target on '{name}.{out_name}' ({od.target_op} {bound_txt}) is pending: "
                    "no computed value yet — run `uel build`",
                    sp,
                )
                continue
            try:
                u = parse_unit(out.unit)
            except UnitError:
                continue
            v_si = u.to_si(float(out.value))
            eps = 1e-9 * max(1.0, abs(bound_si))
            meets = v_si >= bound_si - eps if od.target_op == ">=" else v_si <= bound_si + eps
            half = 0.0
            if isinstance(out.unc, dict) and isinstance(out.unc.get("value"), (int, float)):
                if out.unc.get("kind") == "abs":
                    half = abs(float(out.unc["value"])) * u.factor
                elif out.unc.get("kind") == "rel":
                    half = abs(float(out.value)) * abs(float(out.unc["value"])) * u.factor
            band_crosses = half > 0.0 and (
                (v_si - half < bound_si - eps) if od.target_op == ">=" else (v_si + half > bound_si + eps)
            )
            if not meets:
                bag.error(
                    "UEL0804",
                    f"'{name}.{out_name}' = {out.value:g} {out.unit} violates its target "
                    f"{od.target_op} {bound_txt} ({source})",
                    sp,
                    reason="the target is the acceptance line this output exists to satisfy (ADR-0007); "
                           "a violated target is a red gate, not a footnote",
                )
            elif band_crosses:
                bag.warning(
                    "UEL0804",
                    f"'{name}.{out_name}' = {out.value:g} {out.unit} meets its target "
                    f"{od.target_op} {bound_txt} on the nominal, but its ± band crosses the line",
                    sp,
                    reason="passing-on-the-nominal is the situation a reviewer needs handed to them; "
                           "tighten the inputs or accept the risk in the judgment",
                )

    # -- verify-against contracts: lock-vs-lock cross-checks (ADR-0008) --
    for name in sorted(analyses):
        an = analyses[name]
        sp = span_of(an)
        for i, gv in enumerate(an.verifies):
            if gv.kind != "against": continue
            entry = lock.nodes.get(name)
            out = entry.outputs.get(gv.output) if entry else None
            mine = None
            if out is not None and not isinstance(out.value, list) and out.value is not None:
                try:
                    mine = parse_unit(out.unit).to_si(float(out.value))
                except UnitError:
                    pass
            theirs, their_txt = _ref_si(res, lock, name, i)
            contract = f"verify {gv.output} against {gv.ref}"
            if mine is None or theirs is None:
                bag.info("UEL0809", f"{name}: {contract} is pending — "
                         + ("this output" if mine is None else f"'{gv.ref}'")
                         + " has no computed value yet",
                         sp)
                continue
            if gv.tol_unit:
                try:
                    tol_si = float(gv.tol or 0.0) * parse_unit(gv.tol_unit).factor
                except UnitError:
                    tol_si = 0.0
                ok = abs(mine - theirs) <= tol_si
                band = f"{gv.tol:g} {gv.tol_unit}"
            else:
                tol = float(gv.tol or 0.0)
                ok = abs(mine - theirs) <= tol * max(abs(theirs), 1e-30)
                band = f"{tol * 100:g} %"
            if not ok:
                bag.error(
                    "UEL0808",
                    f"{name}: {contract} FAILED — {out.value:g} {out.unit} vs {their_txt}, "
                    f"outside the declared {band} agreement band",
                    sp,
                    reason="the cross-check oracle is this analysis's declared reason to be believed "
                           "(ADR-0008); fix the core, fix the oracle, or widen the band with a judgment "
                           "that says why",
                )

    # -- maturity: name what still stands on placeholders --
    stubs = sorted(n for n, a in analyses.items() if a.core.lang == "stub")
    for n in stubs:
        bag.info(
            "UEL0807",
            f"'{n}' runs a stub core: its outputs are declared nominals, not analysis",
            span_of(analyses[n]),
            reason=f"{len(stubs)} of {sum(1 for a in analyses.values() if a.core.path or a.core.text)} "
                   "executable nodes are stubs; the status projection carries the ledger",
        )
