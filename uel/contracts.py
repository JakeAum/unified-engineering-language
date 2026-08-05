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
from .diagnostics import Bag, Span
from .lockfile import Lock
from .resolver import Resolution
from .units import UnitError, parse_unit


def _span_of(node: G.Node) -> Span:
    src = getattr(node, "src", "")
    f, _, ln = src.partition(":")
    return Span(f, int(ln) if ln.isdigit() else 0)


def _bound_si(res: Resolution, lock: Lock, node: str, out: str,
              od: G.OutputDecl) -> tuple[float | None, str, str]:
    """(bound in SI-canonical, display text, source description) for a target."""
    if od.target_value is not None:
        q = od.target_value
        if q.value is None or isinstance(q.value, tuple):
            return None, "", ""
        try:
            si = parse_unit(q.unit).to_si(float(q.value))
        except UnitError:
            return None, "", ""
        return si, f"{q.value:g} {q.unit}".strip(), "declared bound"
    rr = res.target_refs.get((node, out))
    if rr is None:
        return None, "", ""
    if rr.kind == "output":
        producer = lock.nodes.get(rr.node)
        oname = rr.target.rsplit(".", 1)[1]
        o = producer.outputs.get(oname) if producer else None
        if o is None or o.value is None or isinstance(o.value, list):
            return None, "", ""
        try:
            si = parse_unit(o.unit).to_si(float(o.value))
        except UnitError:
            return None, "", ""
        return si, f"{o.value:g} {o.unit}".strip(), f"from {rr.target}"
    q = rr.quantity
    if q is None or q.value is None or isinstance(q.value, tuple):
        return None, "", ""
    try:
        si = parse_unit(q.unit).to_si(float(q.value))
    except UnitError:
        return None, "", ""
    return si, f"{q.value:g} {q.unit}".strip(), f"from {rr.target}"


def check(res: Resolution, bag: Bag, lock: Lock) -> None:
    analyses = res.doc.analyses()
    for name in sorted(analyses):
        an = analyses[name]
        sp = _span_of(an)
        for out_name in sorted(an.outputs):
            od = an.outputs[out_name]
            if not od.target_op:
                continue
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

    # -- maturity: name what still stands on placeholders --
    stubs = sorted(n for n, a in analyses.items() if a.core.lang == "stub")
    for n in stubs:
        bag.info(
            "UEL0807",
            f"'{n}' runs a stub core: its outputs are declared nominals, not analysis",
            _span_of(analyses[n]),
            reason=f"{len(stubs)} of {sum(1 for a in analyses.values() if a.core.path or a.core.text)} "
                   "executable nodes are stubs; the status projection carries the ledger",
        )
