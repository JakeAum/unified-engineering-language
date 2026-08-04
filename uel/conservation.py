"""Port and conservation checking (spec §2.2): the physics is the type checker.

Compile-time (static) discipline — no solver runs here. What mathematics
guarantees is checked hard; what is empirical stays an uncertainty-carrying
estimate. Concretely:

- every connection joins ports of the same domain (UEL0401) with compatible
  directions (UEL0402);
- on every net, declared effort windows must be *contained* in what consumers
  accept (UEL0404) — overlap is not enough; a 6S battery "sometimes inside" a
  17 V absolute maximum is a fried part, not a margin;
- per net, worst-case declared draw must not exceed declared supply (UEL0403),
  via interval arithmetic over the flow attribute (per-domain incidence);
- per component, when ports declare `power` (and optionally a `dissipation`
  quantity), energy balance feasibility is checked: in ⊇ out + dissipation;
- budget rollups over the containment tree (spec §7.3): mass and unit_cost sum,
  lead_time is max-over-path; physical realizations stand in for their
  functional identities; geometry-produced masses come from the lock; margins
  are computed and over-budget is UEL0405;
- `in` ports left unconnected are flagged (UEL0406, warning).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import graph as G
from .diagnostics import Bag, Span
from .lockfile import Lock
from .resolver import Resolution
from .units import UnitError, parse_unit

Interval = tuple[float, float]


def _span_of(node: G.Node) -> Span:
    src = getattr(node, "src", "")
    f, _, ln = src.partition(":")
    return Span(f, int(ln) if ln.isdigit() else 0)


def q_interval_si(q: G.Quantity) -> Optional[Interval]:
    """Quantity → SI interval widened by declared uncertainty. None if TBD/unitless-error."""
    if q.value is None:
        return None
    try:
        u = parse_unit(q.unit)
    except UnitError:
        return None
    if isinstance(q.value, tuple):
        lo, hi = u.to_si(q.value[0]), u.to_si(q.value[1])
    else:
        lo = hi = u.to_si(q.value)
    if q.unc.kind == "abs" and q.unc.value:
        d = abs(q.unc.value) * u.factor  # abs unc is in the quantity's unit (linear part)
        lo, hi = lo - d, hi + d
    elif q.unc.kind == "rel" and q.unc.value:
        d = abs(q.unc.value)
        lo, hi = lo - abs(lo) * d, hi + abs(hi) * d
    return (min(lo, hi), max(lo, hi))


def _fmt_si(x: float, unit: str) -> str:
    try:
        u = parse_unit(unit)
        return f"{u.from_si(x):g} {unit}".strip()
    except UnitError:
        return f"{x:g}"


def _fmt_iv(iv: Interval, unit: str) -> str:
    return f"[{_fmt_si(iv[0], unit)}, {_fmt_si(iv[1], unit)}]"


@dataclass
class Net:
    domain: str
    ports: list[tuple[str, str]]  # (component, port)
    src: Span


def _build_nets(res: Resolution, bag: Bag) -> list[Net]:
    doc = res.doc
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    endpoints: dict[tuple[str, str], Span] = {}
    for idx, conn in enumerate(doc.connections):
        pa = tuple(conn.from_ref.split(".", 1))
        pb = tuple(conn.to_ref.split(".", 1))
        if len(pa) != 2 or len(pb) != 2:
            continue
        ca, cb = doc.nodes.get(pa[0]), doc.nodes.get(pb[0])
        if not (isinstance(ca, G.Component) and isinstance(cb, G.Component)):
            continue
        porta, portb = ca.ports.get(pa[1]), cb.ports.get(pb[1])
        if porta is None or portb is None:
            continue
        f, _, ln = conn.src.partition(":")
        csp = Span(f, int(ln) if ln.isdigit() else 0)
        # domain compatibility (UEL0401)
        if porta.domain != portb.domain:
            bag.error(
                "UEL0401",
                f"connection joins '{conn.from_ref}' ({porta.domain}) to '{conn.to_ref}' ({portb.domain})",
                csp,
                reason="a port is a boundary where a conserved quantity crosses; different domains conserve different quantities (spec §2.2)",
            )
            continue
        # direction compatibility (UEL0402)
        if porta.dir == "in" and portb.dir == "in":
            bag.error("UEL0402", f"both '{conn.from_ref}' and '{conn.to_ref}' are 'in' ports", csp)
        if porta.dir == "out" and portb.dir == "out":
            bag.error("UEL0402", f"both '{conn.from_ref}' and '{conn.to_ref}' are 'out' ports", csp)
        union(pa, pb)
        endpoints.setdefault(pa, csp)
        endpoints.setdefault(pb, csp)

    groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for ep in endpoints:
        groups.setdefault(find(ep), []).append(ep)
    nets = []
    for root, eps in sorted(groups.items()):
        comp = res.doc.nodes[eps[0][0]]
        assert isinstance(comp, G.Component)
        nets.append(Net(comp.ports[eps[0][1]].domain, sorted(eps), endpoints[eps[0]]))
    return nets


def _domain_def(res: Resolution, domain: str) -> Optional[G.DomainDef]:
    for cand in (domain, f"lib.domains.{domain}"):
        d = res.doc.nodes.get(cand)
        if isinstance(d, G.DomainDef):
            return d
    return None


def _check_net(res: Resolution, net: Net, bag: Bag) -> None:
    dom = _domain_def(res, net.domain)
    if dom is None or dom.dclass == "data":
        return
    doc = res.doc

    def port(cp: tuple[str, str]) -> G.Port:
        comp = doc.nodes[cp[0]]
        assert isinstance(comp, G.Component)
        return comp.ports[cp[1]]

    # ---- effort window containment (UEL0404): every source window inside every
    # consumer's accepted window (a shared net has one effort) ----
    eff = dom.effort.name
    if eff:
        sources = [(cp, q_interval_si(port(cp).attrs[eff]))
                   for cp in net.ports if port(cp).dir == "out" and eff in port(cp).attrs]
        sinks = [(cp, q_interval_si(port(cp).attrs[eff]))
                 for cp in net.ports if port(cp).dir == "in" and eff in port(cp).attrs]
        unit = dom.effort.unit
        for (scp, siv) in sources:
            for (kcp, kiv) in sinks:
                if siv is None or kiv is None:
                    continue
                if siv[0] < kiv[0] - 1e-12 or siv[1] > kiv[1] + 1e-12:
                    bag.error(
                        "UEL0404",
                        f"{net.domain} net: '{'.'.join(scp)}' supplies {eff} {_fmt_iv(siv, unit)}, "
                        f"but '{'.'.join(kcp)}' accepts only {_fmt_iv(kiv, unit)}",
                        _span_of(doc.nodes[scp[0]]),
                        reason="the supplied window must be contained in the accepted window; overlap is not enough — the uncovered region is a real operating point",
                        related=[(f"accepting port on '{kcp[0]}'", _span_of(doc.nodes[kcp[0]]))],
                    )

    # ---- flow feasibility (UEL0403): worst-case draw within declared supply ----
    flo = dom.flow.name
    if flo:
        supply_hi = 0.0
        supply_any = False
        draw_hi = 0.0
        draw_ports = []
        for cp in net.ports:
            p = port(cp)
            if flo not in p.attrs:
                continue
            iv = q_interval_si(p.attrs[flo])
            if iv is None:
                continue
            if p.dir == "out":
                supply_hi += iv[1]
                supply_any = True
            elif p.dir == "in":
                draw_hi += iv[1]
                draw_ports.append(".".join(cp))
        if supply_any and draw_ports and draw_hi > supply_hi * (1 + 1e-12):
            unit = dom.flow.unit
            bag.error(
                "UEL0403",
                f"{net.domain} net: worst-case draw {_fmt_si(draw_hi, unit)} exceeds declared supply "
                f"{_fmt_si(supply_hi, unit)} (draws: {', '.join(draw_ports)})",
                net.src,
                reason="conserved quantities balance at every connection (spec §2.2 kernel invariant); declared capabilities are the static face of that balance",
            )


def _check_component_power_balance(res: Resolution, comp: G.Component, bag: Bag) -> None:
    """When a component's ports declare `power`, energy must balance feasibly:
    sum(in) must intersect sum(out) + dissipation (storage is v0.2)."""
    ins: list[Interval] = []
    outs: list[Interval] = []
    for p in comp.ports.values():
        if "power" not in p.attrs:
            continue
        iv = q_interval_si(p.attrs["power"])
        if iv is None:
            return
        (ins if p.dir == "in" else outs).append(iv)
    if not ins or not outs:
        return
    diss = comp.quantities.get("dissipation")
    div = q_interval_si(diss) if diss else (0.0, 0.0)
    if div is None:
        return
    in_lo, in_hi = sum(i[0] for i in ins), sum(i[1] for i in ins)
    rhs_lo = sum(o[0] for o in outs) + div[0]
    rhs_hi = sum(o[1] for o in outs) + div[1]
    if in_hi < rhs_lo - 1e-12 or in_lo > rhs_hi + 1e-12:
        bag.error(
            "UEL0403",
            f"'{comp.name}': energy balance infeasible — power in [{in_lo:g}, {in_hi:g}] W cannot equal "
            f"power out + dissipation [{rhs_lo:g}, {rhs_hi:g}] W",
            _span_of(comp),
            reason="energy in = energy out + storage + dissipation (spec §2.2); the declared intervals leave no consistent operating point",
        )


# ---------------------------------------------------------------------------
# Budget rollups (spec §7.3)
# ---------------------------------------------------------------------------


@dataclass
class Rollup:
    total: Interval
    parts: list[tuple[str, float, float, int]]  # (leaf, lo, hi, count)
    unknown: list[str]  # leaves with no value


def _realizers(res: Resolution) -> dict[str, list[G.Component]]:
    out: dict[str, list[G.Component]] = {}
    for c in res.doc.components().values():
        if c.realizes:
            out.setdefault(c.realizes, []).append(c)
    return out


def _leaf_quantity(res: Resolution, comp: G.Component, qname: str, lock: Lock) -> Optional[G.Quantity]:
    q = comp.quantities.get(qname)
    if q is not None:
        return q
    if qname == "mass" and comp.geometry:
        entry = lock.nodes.get(comp.geometry)
        out = entry.outputs.get("mass") if entry else None
        if out is not None and isinstance(out.value, (int, float)):
            unc = G.Uncertainty()
            if isinstance(out.unc, dict) and out.unc.get("kind") in ("abs", "rel"):
                unc = G.Uncertainty(out.unc["kind"], out.unc.get("value"))
            return G.Quantity(float(out.value), out.unit, unc,
                              G.Provenance(kind="derived", site=comp.geometry))
    return None


def _rollup(res: Resolution, comp: G.Component, qname: str, mode: str, lock: Lock,
            realizers: dict[str, list[G.Component]], bag: Bag,
            _seen: frozenset = frozenset()) -> Rollup:
    if comp.name in _seen:  # cycle already diagnosed by the resolver
        return Rollup((0.0, 0.0), [], [])
    _seen = _seen | {comp.name}

    # a physical realization stands in for the functional identity
    target = comp
    if comp.level != "physical":
        reals = realizers.get(comp.name, [])
        if len(reals) == 1:
            target = reals[0]
        elif len(reals) > 1:
            bag.warning(
                "UEL0405",
                f"'{comp.name}' has {len(reals)} physical realizations ({', '.join(r.name for r in reals)}); "
                f"rollup of '{qname}' is indeterminate without a configuration (v0.2)",
                _span_of(comp),
            )
    q = _leaf_quantity(res, target, qname, lock)
    if not target.contains and q is None and not comp.contains:
        return Rollup((0.0, 0.0), [], [f"{target.name}"])
    if q is not None and not target.contains:
        iv = q_interval_si(q)
        if iv is None:
            return Rollup((0.0, 0.0), [], [target.name])
        return Rollup(iv, [(target.name, iv[0], iv[1], 1)], [])

    total: Interval = (0.0, 0.0)
    parts: list[tuple[str, float, float, int]] = []
    unknown: list[str] = []
    for c in target.contains or comp.contains:
        child = res.doc.nodes.get(c.ref)
        if not isinstance(child, G.Component):
            continue
        sub = _rollup(res, child, qname, mode, lock, realizers, bag, _seen)
        if mode == "sum":
            total = (total[0] + sub.total[0] * c.count, total[1] + sub.total[1] * c.count)
        else:  # max
            total = (max(total[0], sub.total[0]), max(total[1], sub.total[1]))
        parts.extend((n, lo, hi, cnt * c.count) for n, lo, hi, cnt in sub.parts)
        unknown.extend(sub.unknown)
    return Rollup(total, parts, unknown)


_ROLLUP_MODES = {"mass": "sum", "unit_cost": "sum", "lead_time": "max"}


def check_budgets(res: Resolution, lock: Lock, bag: Bag) -> dict[tuple[str, str], dict]:
    """Check every budget with a rollup mode; returns computed rollups for
    projections (keyed by (component, budget))."""
    realizers = _realizers(res)
    results: dict[tuple[str, str], dict] = {}
    for comp in res.doc.components().values():
        for bname, budget in comp.budgets.items():
            mode = _ROLLUP_MODES.get(bname)
            if mode is None:
                continue
            roll = _rollup(res, comp, bname, mode, lock, realizers, bag)
            limit_iv = q_interval_si(budget.limit)
            if limit_iv is None:
                continue
            unit = budget.limit.unit
            results[(comp.name, bname)] = {
                "total": roll.total, "limit": limit_iv, "unit": unit,
                "parts": roll.parts, "unknown": roll.unknown, "op": budget.op,
                "at_qty": budget.at_qty,
            }
            if roll.unknown and not roll.parts:
                continue  # nothing known yet; projections will show the hole
            margin = limit_iv[1] - roll.total[1]
            if budget.op == "<=" and roll.total[1] > limit_iv[1] * (1 + 1e-12):
                sev = "error" if roll.total[0] > limit_iv[1] else "warning"
                worst = ", ".join(f"{n}{f' x{c}' if c > 1 else ''} {_fmt_si(hi, unit)}"
                                  for n, lo, hi, c in sorted(roll.parts, key=lambda p: -p[2])[:4])
                msg = (
                    f"budget '{comp.name}.{bname}' {budget.op} {_fmt_si(limit_iv[1], unit)} "
                    f"exceeded: rollup {_fmt_iv(roll.total, unit)}"
                    + (f" (largest: {worst})" if worst else "")
                    + (f"; unvalued leaves: {', '.join(roll.unknown)}" if roll.unknown else "")
                )
                d_kwargs = dict(
                    reason="margin erosion is a computed, watchable property of every budget (spec §2.4); "
                           + ("the whole uncertainty band is over budget" if sev == "error"
                              else "the worst case is over budget; the best case still fits"),
                )
                (bag.error if sev == "error" else bag.warning)("UEL0405", msg, _span_of(comp), **d_kwargs)
                continue
            if roll.unknown:
                bag.info(
                    "UEL0405",
                    f"budget '{comp.name}.{bname}': rollup {_fmt_iv(roll.total, unit)} of "
                    f"{_fmt_si(limit_iv[1], unit)} with unvalued leaves: {', '.join(sorted(set(roll.unknown)))}",
                    _span_of(comp),
                )
    return results


def check_dangling(res: Resolution, bag: Bag) -> None:
    connected: set[tuple[str, str]] = set()
    for conn in res.doc.connections:
        for ref in (conn.from_ref, conn.to_ref):
            parts = ref.split(".", 1)
            if len(parts) == 2:
                connected.add((parts[0], parts[1]))
    for comp in res.doc.components().values():
        for pname, port in comp.ports.items():
            if port.dir == "in" and (comp.name, pname) not in connected:
                dom = _domain_def(res, port.domain)
                if dom is not None and dom.dclass == "data":
                    continue
                bag.warning(
                    "UEL0406",
                    f"'in' port '{comp.name}.{pname}' ({port.domain}) is never connected",
                    _span_of(comp),
                    reason="an unconnected input is either dead (cut it) or a hole in the model (connect it)",
                )


def check(res: Resolution, bag: Bag, lock: Lock | None = None) -> dict:
    lock = lock or Lock()
    nets = _build_nets(res, bag)
    for net in nets:
        _check_net(res, net, bag)
    for comp in res.doc.components().values():
        _check_component_power_balance(res, comp, bag)
    rollups = check_budgets(res, lock, bag)
    check_dangling(res, bag)
    return rollups
