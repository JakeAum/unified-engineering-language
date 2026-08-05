"""Compiled projections (spec §9.1): one graph, many views, zero authored artifacts.

Every projection is stamped with the source graph hash and the staleness state at
compile time — "is this document current?" is a mechanical query, and a stale
traveler on the shop floor is as detectable as a stale CFD case. Hand-editing an
output is the drift failure mode; these files say so in their header — and, since
saying so has never stopped anyone, they also **prove** it: every projection ends
with a digest of its own body, so `uel doctor` can tell a *doctored* report (edited
after compilation, still claiming its graph hash) from a merely *stale* one
(honestly compiled from an older graph). The two failure modes are different
diseases and get different advice.

v0.1 projections: BOM (containment tree with rollups and margins), ICD (per-net
interface control), work instructions (per bound physical part, DFM checks as
inspection steps with as-built write-back targets), status (requirements →
analyses → judgment/freshness/validation).
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from . import graph as G
from .conservation import q_interval_si
from .hashing import graph_hash
from .lockfile import Lock
from .resolver import Resolution
from .staleness import compute
from .units import UnitError, parse_unit


INTEGRITY_PREFIX = "> Integrity: body "


def seal(text: str) -> str:
    """Append the body digest that makes a projection self-authenticating.

    The digest covers everything above it, so recomputation is exact and needs
    no re-render: a body that no longer hashes to its own footer was edited
    after compilation. This is integrity, not security — anyone can recompute
    a digest for edited text. It catches the failure mode that actually
    happens (someone fixes a number in the traveler instead of the model), not
    an adversary.
    """
    body = text if text.endswith("\n") else text + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return f"{body}{INTEGRITY_PREFIX}sha256:{digest}\n"


def verify_seal(text: str) -> tuple[bool, str, str]:
    """(intact, recorded, recomputed) for a projection's integrity footer.
    `recorded` is "" when the artifact carries no footer at all."""
    lines = text.splitlines(keepends=True)
    idx = next((i for i in range(len(lines) - 1, -1, -1)
                if lines[i].startswith(INTEGRITY_PREFIX)), None)
    if idx is None:
        return False, "", ""
    recorded = lines[idx][len(INTEGRITY_PREFIX):].strip()
    body = "".join(lines[:idx])
    recomputed = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return recorded == recomputed, recorded, recomputed


def _hdr(title: str, res: Resolution, lock: Lock) -> list[str]:
    h = graph_hash(res.doc, res.project.tolerances)[7:19]
    rep = compute(res, lock)
    stale = rep.stale()
    stamp = f"graph {h} · edition {res.doc.edition} · {len(res.doc.nodes)} nodes"
    lines = [f"# {title}", ""]
    lines.append(f"> **Compiled projection — do not hand-edit** (spec §9.1). {stamp}.")
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    lines.append(f"> Compiled {ts}.")
    if stale:
        lines.append(f">")
        lines.append(f"> ⚠ **STALE SOURCE**: {len(stale)} of {len(rep.order)} executable nodes are not fresh "
                     f"({', '.join(stale[:6])}{'…' if len(stale) > 6 else ''}). "
                     f"Numbers below may not reflect the current model. Run `uel build`.")
    lines.append("")
    return lines


def _fmt_q(q: G.Quantity | None, target_unit: str = "") -> str:
    if q is None or q.value is None:
        return "—"
    unit = target_unit or q.unit
    try:
        u_from = parse_unit(q.unit)
        u_to = parse_unit(unit)
        conv = lambda v: u_to.from_si(u_from.to_si(v))
    except UnitError:
        conv = lambda v: v
        unit = q.unit
    if isinstance(q.value, tuple):
        s = f"[{conv(q.value[0]):g}, {conv(q.value[1]):g}] {unit}"
    else:
        s = f"{conv(q.value):g} {unit}"
    if q.unc.kind == "abs" and q.unc.value is not None:
        s += f" ± {q.unc.value:g}"
    elif q.unc.kind == "rel" and q.unc.value is not None:
        s += f" ± {q.unc.value * 100:g}%"
    elif q.unc.kind == "cal":
        s += " ± cal"
    if q.prov.kind == "measured":
        s += " ✓meas"
    return s.strip()


def _si_range_str(iv: tuple[float, float] | None, unit: str) -> str:
    if iv is None:
        return "—"
    try:
        u = parse_unit(unit)
        lo, hi = u.from_si(iv[0]), u.from_si(iv[1])
    except UnitError:
        lo, hi = iv
    if abs(lo - hi) < 1e-12:
        return f"{lo:g} {unit}".strip()
    return f"[{lo:g}, {hi:g}] {unit}".strip()


# ---------------------------------------------------------------------------
# BOM
# ---------------------------------------------------------------------------


def bom(res: Resolution, lock: Lock, rollups: dict) -> str:
    doc = res.doc
    lines = _hdr("Bill of Materials", res, lock)
    comps = doc.components()
    contained = {c.ref for comp in comps.values() for c in comp.contains}
    # roots: nobody contains them, and they aren't the physical half of a binding
    # (realizers surface inline on their functional identity's row)
    roots = [n for n, c in comps.items() if n not in contained and not c.realizes]
    realizers: dict[str, G.Component] = {}
    for c in comps.values():
        if c.realizes:
            realizers.setdefault(c.realizes, c)

    lines.append("| Item | Realization | Qty | Material | Process | Mass | Unit cost | Lead |")
    lines.append("|---|---|---|---|---|---|---|---|")

    def leaf_q(comp: G.Component, qname: str) -> G.Quantity | None:
        q = comp.quantities.get(qname)
        if q is not None:
            return q
        if qname == "mass" and comp.geometry:
            e = lock.nodes.get(comp.geometry)
            o = e.outputs.get("mass") if e else None
            if o is not None and isinstance(o.value, (int, float)):
                return G.Quantity(float(o.value), o.unit)
        return None

    def emit(name: str, count: int, depth: int) -> None:
        comp = comps.get(name)
        if comp is None:
            return
        target = realizers.get(name, comp) if comp.level != "physical" else comp
        indent = "&nbsp;" * (depth * 3)
        real = target.name if target is not comp else ("·" if comp.level == "physical" else "**unbound**")
        mat = target.material.removeprefix("lib.materials.") if target.material else "—"
        proc = target.process.removeprefix("lib.process.") if target.process else "—"
        mass = _fmt_q(leaf_q(target, "mass"), "g")
        cost = _fmt_q(leaf_q(target, "unit_cost"), "USD")
        lead = _fmt_q(leaf_q(target, "lead_time"), "week")
        lines.append(f"| {indent}{name} | {real} | {count} | {mat} | {proc} | {mass} | {cost} | {lead} |")
        for c in (target.contains or comp.contains):
            emit(c.ref, c.count, depth + 1)

    for r in sorted(roots):
        emit(r, 1, 0)

    if rollups:
        lines.append("")
        lines.append("## Budget rollups")
        lines.append("")
        lines.append("| Budget | Limit | Rollup (worst) | Margin | Unvalued leaves |")
        lines.append("|---|---|---|---|---|")
        for (cname, bname), r in sorted(rollups.items()):
            unit = r["unit"]
            limit, total = r["limit"][1], r["total"][1]
            margin = limit - total
            mark = "✅" if margin >= 0 else "❌"
            lines.append(
                f"| {cname}.{bname} | {_si_range_str((limit, limit), unit)} "
                f"| {_si_range_str(r['total'], unit)} | {mark} {_si_range_str((margin, margin), unit)} "
                f"| {', '.join(sorted(set(r['unknown']))) or '—'} |"
            )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ICD
# ---------------------------------------------------------------------------


def icd(res: Resolution, lock: Lock) -> str:
    from .conservation import _build_nets  # shared net construction
    from .diagnostics import Bag

    lines = _hdr("Interface Control Document", res, lock)
    nets = _build_nets(res, Bag())  # diagnostics already surfaced by check
    if not nets:
        lines.append("*No connections in the graph.*")
        return "\n".join(lines) + "\n"
    doc = res.doc
    for i, net in enumerate(nets, 1):
        dom = None
        for cand in (net.domain, f"lib.domains.{net.domain}"):
            d = doc.nodes.get(cand)
            if isinstance(d, G.DomainDef):
                dom = d
                break
        lines.append(f"## Net {i} — `{net.domain}`" + (f" ({dom.dclass})" if dom else ""))
        lines.append("")
        lines.append("| Port | Direction | " +
                     (f"{dom.effort.name} | {dom.flow.name} |" if dom and dom.effort.name
                      else "Protocol | Attributes |"))
        lines.append("|---|---|---|---|")
        for (cname, pname) in net.ports:
            comp = doc.nodes[cname]
            assert isinstance(comp, G.Component)
            port = comp.ports[pname]
            if dom and dom.effort.name:
                eff = _si_range_str(
                    q_interval_si(port.attrs[dom.effort.name]), dom.effort.unit
                ) if dom.effort.name in port.attrs else "—"
                flo = _si_range_str(
                    q_interval_si(port.attrs[dom.flow.name]), dom.flow.unit
                ) if dom.flow.name in port.attrs else "—"
                lines.append(f"| `{cname}.{pname}` | {port.dir} | {eff} | {flo} |")
            else:
                attrs = ", ".join(f"{k}={_fmt_q(v)}" for k, v in port.attrs.items()) or "—"
                lines.append(f"| `{cname}.{pname}` | {port.dir} | {port.protocol or '—'} | {attrs} |")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Work instructions
# ---------------------------------------------------------------------------


def work_instructions(res: Resolution, lock: Lock) -> str:
    doc = res.doc
    lines = _hdr("Work Instructions", res, lock)
    lines.append("*Travelers are compiled projections AND data-entry surfaces (spec §8.2): every*")
    lines.append("*measurement step names its write-back target — record as-built values with*")
    lines.append("*`uel calibrate` so reality lands back in the graph.*")
    lines.append("")
    any_part = False
    for name, comp in sorted(doc.components().items()):
        if comp.level != "physical" or not comp.process:
            continue
        any_part = True
        proc = doc.nodes.get(comp.process)
        pname = comp.process.removeprefix("lib.process.")
        lines.append(f"## {name}" + (f" (realizes {comp.realizes})" if comp.realizes else ""))
        lines.append("")
        mat = comp.material.removeprefix("lib.materials.") if comp.material else "—"
        geom_hash = ""
        if comp.geometry:
            e = lock.nodes.get(comp.geometry)
            geom_hash = f" · geometry `{comp.geometry}` @ {e.recipe[7:19]}" if e and e.recipe else f" · geometry `{comp.geometry}` (UNBUILT)"
        lines.append(f"Process **{pname}** · material **{mat}**{geom_hash}")
        lines.append("")
        step = 1
        lines.append(f"{step}. Verify material lot is {mat}; record lot number: `________`")
        step += 1
        if isinstance(proc, G.ProcessDef):
            for rname, rule in sorted(proc.rules.items()):
                if rule.op in (">=", "<="):
                    lim = ""
                    if rule.limit and rule.limit.value is not None and not isinstance(rule.limit.value, tuple):
                        lim = f" (require {rule.op} {rule.limit.value:g} {rule.limit.unit})"
                    lines.append(f"{step}. Inspect `{rule.feature}`{lim}: measured `________`"
                                 + (f" — *{rule.message}*" if rule.message else ""))
                    step += 1
        lines.append(f"{step}. Weigh finished part; write back: "
                     f"`uel calibrate` target `{name}.mass`, measured `________ g`")
        step += 1
        lines.append(f"{step}. Any substitution, shim, or impossible step: file an as-built delta "
                     f"against `{name}` — the model must follow the metal, not the reverse.")
        lines.append("")
    if not any_part:
        lines.append("*No bound physical parts with processes in the graph yet.*")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Status / traceability
# ---------------------------------------------------------------------------


def status(res: Resolution, lock: Lock) -> str:
    doc = res.doc
    rep = compute(res, lock)
    lines = _hdr("Requirement Status & Traceability", res, lock)
    reqs = doc.requirements()
    analyses = doc.analyses()
    by_req: dict[str, list[str]] = {}
    for aname, an in analyses.items():
        if an.intent.ref:
            by_req.setdefault(an.intent.ref, []).append(aname)
    lines.append("| Requirement | Text | Analyses | Judgment | Freshness | Validation |")
    lines.append("|---|---|---|---|---|---|")
    for rname, req in sorted(reqs.items()):
        served = sorted(by_req.get(rname, []))
        if not served:
            lines.append(f"| `{rname}` | {req.text or '—'} | **none** | — | — | — |")
            continue
        for aname in served:
            an = analyses[aname]
            st = rep.states.get(aname)
            fresh = st.status if st else "n/a"
            entry = lock.nodes.get(aname)
            validation = "—"
            if entry and entry.run.get("validation"):
                vs = entry.run["validation"]
                marks = []
                for out, v in sorted(vs.items()):
                    ok = v.get("verdict") in ("consistent", "tightening")
                    marks.append(("✅" if ok else "❌") + f" {out} ({v.get('source', '?')})")
                validation = "; ".join(marks)
            lines.append(
                f"| `{rname}` | {req.text or '—'} | `{aname}` | {an.judgment.status} "
                f"| {fresh} | {validation} |"
            )
    orphans = sorted(a for a, an in analyses.items()
                     if not an.intent.ref and an.akind == "analysis")
    if orphans:
        lines.append("")
        lines.append(f"**Analyses with no recorded intent** (an answer detached from its intent "
                     f"is meaningless, spec §3.1): {', '.join(f'`{o}`' for o in orphans)}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DOT export
# ---------------------------------------------------------------------------


def dot(res: Resolution) -> str:
    doc = res.doc
    out = ["digraph uel {", '  rankdir=LR;', '  node [fontname="Helvetica", fontsize=10];']
    shapes = {
        "component": ("box", "#e8f0fe"),
        "analysis": ("ellipse", "#fef7e0"),
        "requirement": ("note", "#e6f4ea"),
    }

    def nid(name: str) -> str:
        return '"' + name.replace('"', "") + '"'

    for name, node in sorted(doc.nodes.items()):
        if name.startswith("lib."):
            continue
        kind = node.KIND
        if kind == "analysis" and getattr(node, "akind", "") == "geometry":
            shape, color = "component", "#fce8e6"
        elif kind in shapes:
            shape, color = shapes[kind]
        else:
            continue
        label = name
        if isinstance(node, G.Component):
            label = f"{name}\\n[{node.level}]"
        out.append(f'  {nid(name)} [shape={shape}, style=filled, fillcolor="{color}", label="{label}"];')
    for (consumer, local), rr in sorted(res.known_refs.items()):
        if rr.node.startswith("lib."):
            continue
        out.append(f'  {nid(rr.node)} -> {nid(consumer)} [label="{local}", fontsize=8, color="#5f6368"];')
    for conn in doc.connections:
        a, b = conn.from_ref.split(".")[0], conn.to_ref.split(".")[0]
        out.append(f'  {nid(a)} -> {nid(b)} [style=bold, color="#1a73e8", dir=both, arrowhead=none, arrowtail=none];')
    for name, comp in sorted(doc.components().items()):
        for c in comp.contains:
            out.append(f'  {nid(name)} -> {nid(c.ref)} [style=dashed, color="#188038", arrowhead=odiamond];')
        if comp.realizes:
            out.append(f'  {nid(comp.realizes)} -> {nid(name)} [style=dotted, color="#9334e6", label="realizes", fontsize=8];')
    for aname, an in sorted(doc.analyses().items()):
        if an.intent.ref and not an.intent.ref.startswith("lib."):
            out.append(f'  {nid(an.intent.ref)} -> {nid(aname)} [style=dotted, color="#137333", label="intent", fontsize=8];')
    out.append("}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Provenance query
# ---------------------------------------------------------------------------


def provenance(res: Resolution, target: str, lock: Lock) -> str:
    from .calibration import load_overlay

    lines: list[str] = []
    doc = res.doc

    if ".outputs." in target:
        node_name, out_name = target.split(".outputs.", 1)
        an = doc.nodes.get(node_name)
        if not isinstance(an, G.Analysis) or out_name not in an.outputs:
            return f"provenance: '{target}' is not a declared analysis output"
        entry = lock.nodes.get(node_name)
        lines.append(f"{target}")
        if entry and out_name in entry.outputs:
            o = entry.outputs[out_name]
            lines.append(f"  value    {o.value} {o.unit}  (hash {o.hash[7:19]})")
            lines.append(f"  computed by '{node_name}' ({an.core.path}), "
                         f"run {entry.run.get('ts', '?')} in {entry.run.get('wall_s', '?')}s")
        else:
            lines.append(f"  value    never computed (run `uel build`)")
        lines.append(f"  intent   {an.intent.ref or '—'}"
                     + (f' "{an.intent.text}"' if an.intent.text else ""))
        for local, ref in sorted(an.knowns.items()):
            lines.append(f"  known    {local} <- {ref}")
        if an.framing.envelope.claims:
            for c, r in sorted(an.framing.envelope.claims.items()):
                lines.append(f"  assumes  {c}" + (f' because "{r}"' if r else ""))
    else:
        from .calibration import _find_quantity

        q = _find_quantity(res, target)
        if q is None:
            return f"provenance: '{target}' does not name a quantity"
        lines.append(f"{target}")
        val = list(q.value) if isinstance(q.value, tuple) else q.value
        lines.append(f"  value    {val} {q.unit}".rstrip())
        lines.append(f"  origin   {q.prov.kind}"
                     + (f" — {q.prov.detail}" if q.prov.detail else "")
                     + (f" ({q.prov.ts})" if q.prov.ts else ""))
        lines.append(f"  declared {q.prov.site}" if q.prov.kind != "measured" else
                     f"  applied  from {q.prov.site}")
        history = load_overlay(res.project.root).get(target, [])
        for h in history:
            mark = {"tightening": "tightened", "discrepancy": "DISCREPANCY"}.get(
                h.get("verdict", ""), h.get("verdict", ""))
            lines.append(f"  history  {h.get('ts', '?')}: {h.get('value')} {h.get('unit')} "
                         f"({h.get('source', '?')}) {mark}".rstrip())

    consumers = sorted(c for (c, _), rr in res.known_refs.items() if rr.target == target)
    if consumers:
        lines.append(f"  consumed by {', '.join(consumers)}")
    return "\n".join(lines)
