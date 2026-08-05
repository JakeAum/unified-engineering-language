"""Compiled projections (spec §9.1): one graph, many views, zero authored artifacts.

Every projection is stamped with the source graph hash and the staleness state at
compile time — "is this document current?" is a mechanical query, and a stale
traveler on the shop floor is as detectable as a stale CFD case. Hand-editing an
output is the drift failure mode; these files say so in their header.

v0.1 projections: BOM (containment tree with rollups and margins), ICD (per-net
interface control), work instructions (per bound physical part, DFM checks as
inspection steps with as-built write-back targets), status (requirements →
analyses → judgment/freshness/validation).
"""

from __future__ import annotations

import time
from pathlib import Path

from . import graph as G
from .conservation import q_interval_si
from .hashing import graph_hash
from .lockfile import Lock
from .resolver import Resolution
from .staleness import compute
from .units import UnitError, parse_unit

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
    if q is None or q.value is None: return "—"
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
    if iv is None: return "—"
    try:
        u = parse_unit(unit)
        lo, hi = u.from_si(iv[0]), u.from_si(iv[1])
    except UnitError:
        lo, hi = iv
    if abs(lo - hi) < 1e-12: return f"{lo:g} {unit}".strip()
    return f"[{lo:g}, {hi:g}] {unit}".strip()

# BOM

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
        if q is not None: return q
        if qname == "mass" and comp.geometry:
            e = lock.nodes.get(comp.geometry)
            o = e.outputs.get("mass") if e else None
            if o is not None and isinstance(o.value, (int, float)):
                return G.Quantity(float(o.value), o.unit)
        return None

    def emit(name: str, count: int, depth: int) -> None:
        comp = comps.get(name)
        if comp is None: return
        target = realizers.get(name, comp) if comp.level != "physical" else comp
        indent = "&nbsp;" * (depth * 3)
        real = target.name if target is not comp else ("·" if comp.level == "physical" else "**unbound**")
        mat = target.material.removeprefix("lib.materials.") if target.material else "—"
        proc = target.process.removeprefix("lib.process.") if target.process else "—"
        mass = _fmt_q(leaf_q(target, "mass"), "g")
        cost = _fmt_q(leaf_q(target, "unit_cost"), "USD")
        lead = _fmt_q(leaf_q(target, "lead_time"), "week")
        # instance designators (v0.2): `contains X x N` mints addressable slots —
        # the names per-serial overlays (calibration/<designator>.json) target
        qty = str(count)
        if count > 1:
            short = name.rsplit(".", 1)[-1]
            qty = (f"{count} ({', '.join(f'{short}#{i}' for i in range(1, count + 1))})"
                   if count <= 4 else f"{count} ({short}#1…#{count})")
        lines.append(f"| {indent}{name} | {real} | {qty} | {mat} | {proc} | {mass} | {cost} | {lead} |")
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

# ICD

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

# Work instructions

def work_instructions(res: Resolution, lock: Lock) -> str:
    doc = res.doc
    lines = _hdr("Work Instructions", res, lock)
    lines.append("*Travelers are compiled projections AND data-entry surfaces (spec §8.2): every*")
    lines.append("*measurement step names its write-back target — record as-built values with*")
    lines.append("*`uel calibrate` so reality lands back in the graph.*")
    lines.append("")
    any_part = False
    for name, comp in sorted(doc.components().items()):
        if comp.level != "physical" or not comp.process: continue
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

# Status / traceability

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

    # -- targets: acceptance computed, not narrated (v0.2, ADR-0007) --
    from .contracts import _bound_si

    trows: list[str] = []
    for aname, an in sorted(analyses.items()):
        for oname in sorted(an.outputs):
            od = an.outputs[oname]
            if not od.target_op: continue
            bound_si, bound_txt, source = _bound_si(res, lock, aname, oname, od)
            entry = lock.nodes.get(aname)
            out = entry.outputs.get(oname) if entry else None
            if out is None or out.value is None or isinstance(out.value, list) or bound_si is None:
                verdict, shown = "⏳ pending", "—"
            else:
                try:
                    v_si = parse_unit(out.unit).to_si(float(out.value))
                except UnitError:
                    continue
                meets = v_si >= bound_si if od.target_op == ">=" else v_si <= bound_si
                verdict = "✅ meets" if meets else "❌ VIOLATED"
                shown = f"{out.value:g} {out.unit}"
            trows.append(f"| `{aname}.{oname}` | {od.target_op} {bound_txt} ({source}) "
                         f"| {shown} | {verdict} |")
    if trows:
        lines.append("")
        lines.append("## Targets")
        lines.append("")
        lines.append("| Output | Target | Computed | Verdict |")
        lines.append("|---|---|---|---|")
        lines.extend(trows)

    # -- hazard coverage (v0.6): the questions the models cannot ask, answered --
    models = doc.models()
    hrows: list[str] = []
    if models:
        covered_by: dict[str, list[str]] = {}
        for aname in sorted(analyses):
            for c in analyses[aname].framing.covers:
                covered_by.setdefault(c, []).append(aname)
        for mname in sorted(models):
            md = models[mname]
            short = mname.removeprefix("lib.models.")
            users = sorted(a for a, an in analyses.items() if an.framing.model == short)
            if not users: continue
            for hz in sorted(md.hazards):
                if hz in covered_by:
                    verdict = "✅ covered by " + ", ".join(f"`{c}`" for c in covered_by[hz])
                else:
                    waivers = [(a, analyses[a].framing.waives[hz]) for a in users
                               if hz in analyses[a].framing.waives]
                    if waivers and len(waivers) == len(users):
                        verdict = "; ".join(f"waived by `{a}`: “{r}”" for a, r in waivers)
                    elif waivers:
                        open_users = [a for a in users if hz not in analyses[a].framing.waives]
                        verdict = ("⚠ **OPEN** for " + ", ".join(f"`{a}`" for a in open_users)
                                   + "; " + "; ".join(f"waived by `{a}`" for a, _ in waivers))
                    else:
                        verdict = "⚠ **OPEN** — " + md.hazards[hz]
                hrows.append(f"| `{short}` | {hz} | {', '.join(f'`{u}`' for u in users)} | {verdict} |")
    if hrows:
        lines.append("")
        lines.append("## Hazard coverage (what the models cannot see, v0.6)")
        lines.append("")
        lines.append("| Model | Hazard | Used by | Answered |")
        lines.append("|---|---|---|---|")
        lines.extend(hrows)

    # -- maturity + verification ledger (v0.2/v0.3): where belief is load-bearing --
    kinds: dict[str, list[str]] = {"python": [], "expr": [], "stub": []}
    for aname, an in sorted(analyses.items()):
        if an.core.path or an.core.text:
            kinds.setdefault(an.core.lang, []).append(aname)
    total = sum(len(v) for v in kinds.values())
    if total:
        lines.append("")
        lines.append("## Maturity and verification")
        lines.append("")
        lines.append(f"{total} executable nodes: "
                     f"{len(kinds['expr'])} expr (kernel-checked formulas), "
                     f"{len(kinds['python'])} python (opaque cores), "
                     f"{len(kinds['stub'])} stub (declared nominals).")
        if kinds["stub"]:
            lines.append("")
            lines.append("**Still standing on stubs**: "
                         + ", ".join(f"`{n}`" for n in kinds["stub"])
                         + " — every number downstream of these is a placeholder.")
        naked: list[str] = []
        contracted: list[str] = []
        for aname in kinds["python"]:
            an = analyses[aname]
            if not an.verifies:
                naked.append(aname)
                continue
            entry = lock.nodes.get(aname)
            recs = (entry.run.get("verify", []) if entry else []) or []
            marks = []
            n_against = sum(1 for v in an.verifies if v.kind == "against")
            if n_against:
                marks.append(f"against×{n_against}")
            for r in recs:
                marks.append(("✅" if r.get("ok") else "❌") + " " + str(r.get("contract", "")).removeprefix("verify "))
            contracted.append(f"`{aname}` ({'; '.join(marks)})")
        if contracted:
            lines.append("")
            lines.append("**Verified by contract** (ADR-0008): " + "; ".join(contracted))
        if naked:
            lines.append("")
            lines.append("**Trusted on the author's word** (no contract): "
                         + ", ".join(f"`{n}`" for n in sorted(naked))
                         + " — the review dossier (`uel pack`) marks these; belief is load-bearing here.")
    lines.append("")
    return "\n".join(lines)

# DOT export

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
        if name.startswith("lib."): continue
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
        if rr.node.startswith("lib."): continue
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

# The review dossier (v0.3, ADR-0008): `uel pack <node>`

def pack(res: Resolution, lock: Lock, node_name: str) -> str:
    """One node's full epistemic chain, sized for a reviewing agent's context.

    The zero-trust posture made operational: everything needed to audit this
    claim without believing its author — the intent, the framing, every value
    flowing in with its provenance, the argument itself (expr body verbatim, a
    size-capped python source, or the black box's interface manifest), the
    verification contracts with their latest verdicts, the acceptance targets,
    the blast radius, and the content hashes to cite. Deliberately bounded:
    upstream nodes appear as one-line summaries — pack them separately."""
    doc = res.doc
    an = doc.nodes.get(node_name)
    if an is None: return f"pack: no node named '{node_name}'\n"
    if not isinstance(an, G.Analysis):
        return (f"pack: '{node_name}' is a {an.KIND}; the dossier covers analyses — "
                f"try `uel query provenance` for values\n")

    rep = compute(res, lock)
    st = rep.states.get(node_name)
    entry = lock.nodes.get(node_name)
    root = res.project.root
    L: list[str] = []

    h = graph_hash(doc, res.project.tolerances)[7:19]
    L.append(f"# Review dossier — {node_name}")
    L.append("")
    L.append(f"> Compiled projection (spec §9.1) — graph {h} · edition {doc.edition}.")
    if st is not None:
        mark = "FRESH" if st.status == "fresh" else st.status.upper()
        L.append(f"> State: **{mark}**"
                 + (f" — {'; '.join(st.reasons)}" if st.status != "fresh" and st.reasons else "")
                 + (". Numbers below are the current lock." if st.status == "fresh"
                    else ". **Rebuild before trusting numbers below.**"))
    L.append("")

    # -- the claim --
    L.append("## Claim")
    L.append("")
    if an.intent.ref:
        req = doc.nodes.get(an.intent.ref)
        rtext = f" — “{req.text}”" if isinstance(req, G.Requirement) and req.text else ""
        L.append(f"- intent: `{an.intent.ref}`{rtext}")
        if an.intent.text:
            L.append(f"- the question: “{an.intent.text}”")
    else:
        L.append("- **no recorded intent** — an answer detached from its intent is meaningless (spec §3.1)")
    if an.doc:
        L.append(f"- doc: {an.doc}")
    L.append("")

    # -- the framing --
    L.append("## Framing (the fence this argument lives inside)")
    L.append("")
    if an.framing.model:
        L.append(f"- model: `{an.framing.model}`")
        md = next((n for cand in (an.framing.model, f"lib.models.{an.framing.model}")
                   if isinstance(n := doc.nodes.get(cand), G.ModelDef)), None)
        if md is not None:
            for hz, why in sorted(md.hazards.items()):
                if hz in an.framing.waives:
                    L.append(f"- hazard `{hz}` waived: “{an.framing.waives[hz]}”")
                else:
                    cov = sorted(a for a, o in doc.analyses().items() if hz in o.framing.covers)
                    L.append(f"- hazard `{hz}` ({why}) — "
                             + (f"covered by {', '.join(f'`{c}`' for c in cov)}" if cov
                                else "**OPEN**"))
    for c in an.framing.covers:
        L.append(f"- covers `{c}` — this analysis is the answer to that hazard")
    for c, r in sorted(an.framing.envelope.claims.items()):
        L.append(f"- assumes `{c}`" + (f" because “{r}”" if r else ""))
    for c, r in sorted(an.framing.envelope.requires.items()):
        L.append(f"- requires `{c}` of upstream" + (f" because “{r}”" if r else ""))
    for var, p in sorted(an.framing.envelope.predicates.items()):
        L.append(f"- valid only for `{var}` in {_fmt_pred_text(p)}")
    if not (an.framing.model or not an.framing.envelope.is_empty()):
        L.append("- (no declared framing)")
    L.append("")

    # -- what flows in --
    L.append("## Knowns (every value flowing in — references, never copies)")
    L.append("")
    L.append("| local | from | value | provenance |")
    L.append("|---|---|---|---|")
    for local in sorted(an.knowns):
        rr = res.known_refs.get((node_name, local))
        if rr is None:
            L.append(f"| {local} | {an.knowns[local]} | *unresolved* | — |")
            continue
        if rr.kind == "output":
            pe = lock.nodes.get(rr.node)
            o = pe.outputs.get(rr.target.rsplit('.', 1)[1]) if pe else None
            val = _lock_out_text(o) if o else "*not built*"
            prov = f"computed by `{rr.node}`"
        else:
            q = rr.quantity
            val = _fmt_q(q)
            prov = q.prov.kind + (f" — {q.prov.detail}" if q.prov.detail else "") if q else "—"
        fence = an.framing.envelope.predicates.get(local)
        if fence is not None:
            val += f" · fenced {_fmt_pred_text(fence)}"
        L.append(f"| {local} | `{rr.target}` | {val} | {prov} |")
    if an.params:
        L.append("")
        L.append("**Params (node-local literals):** "
                 + "; ".join(f"`{k}` = {_fmt_q(q)}"
                             + (f" ({q.prov.detail})" if q.prov.detail else "")
                             for k, q in sorted(an.params.items())))
    L.append("")

    # -- the argument itself --
    L.append("## The argument (core)")
    L.append("")
    L.extend(_pack_core(an, root))
    L.append("")

    # -- verification --
    L.append("## Verification (reasons to believe, graded by the kernel)")
    L.append("")
    basis = {"expr": "**by construction** — the formula above is type-checked "
                     "(dimensions + levels) and kernel-evaluated",
             "stub": "**none** — declared nominal; no analysis stands behind these numbers",
             "python": None}[an.core.lang if an.core.lang in ("expr", "stub") else "python"]
    if basis:
        L.append(f"- {basis}")
    if an.verifies:
        recorded = {r.get("contract"): r for r in (entry.run.get("verify", []) if entry else [])}
        from .contracts import _ref_si
        for i, v in enumerate(an.verifies):
            if v.kind == "against":
                theirs, ttxt = _ref_si(res, lock, node_name, i)
                o = entry.outputs.get(v.output) if entry else None
                verdict = "⏳ pending"
                if o is not None and theirs is not None and not isinstance(o.value, list):
                    try:
                        mine = parse_unit(o.unit).to_si(float(o.value))
                        if v.tol_unit:
                            ok = abs(mine - theirs) <= float(v.tol or 0) * parse_unit(v.tol_unit).factor
                        else:
                            ok = abs(mine - theirs) <= float(v.tol or 0) * max(abs(theirs), 1e-30)
                        verdict = f"✅ agrees with {ttxt}" if ok else f"❌ DISAGREES with {ttxt}"
                    except UnitError:
                        pass
                band = f"{(v.tol or 0) * 100:g} %" if not v.tol_unit else f"{v.tol:g} {v.tol_unit}"
                L.append(f"- cross-check: `{v.output}` vs `{v.ref}` within {band} — {verdict}")
            else:
                key = (f"verify {v.output} monotone with {v.known} {v.direction}"
                       if v.kind == "monotone"
                       else f"verify converged {v.output} <= {v.tol:g}"
                       if v.kind == "converged" else f'verify case "{v.path}"')
                r = recorded.get(key)
                verdict = ("✅ " + r.get("detail", "held") if r and r.get("ok")
                           else "❌ " + r.get("detail", "failed") if r
                           else "⏳ not yet probed (runs at build)")
                L.append(f"- {key} — {verdict}")
    elif an.core.lang not in ("expr", "stub"):
        L.append("- **trusted (no contract)** — this core is believed on its author's word; "
                 "consider `verify` contracts (ADR-0008)")
    L.append("")

    # -- what comes out --
    L.append("## Outputs")
    L.append("")
    L.append("| output | type | computed | target | measured |")
    L.append("|---|---|---|---|---|")
    validation = (entry.run.get("validation", {}) if entry else {}) or {}
    for oname in sorted(an.outputs):
        od = an.outputs[oname]
        o = entry.outputs.get(oname) if entry else None
        val = _lock_out_text(o) if o else "*not built*"
        tgt = "—"
        if od.target_op:
            bound = od.target_ref or (_fmt_q(od.target_value) if od.target_value else "?")
            tgt = f"{od.target_op} {bound}"
        meas = "—"
        vv = validation.get(oname)
        if vv:
            mark = "✅" if vv.get("verdict") in ("consistent", "tightening") else "❌"
            meas = f"{mark} {vv.get('measured')} {vv.get('unit', '')} ({vv.get('source', '?')})"
        ty = "artifact" if od.artifact else (od.unit or "dimensionless")
        L.append(f"| {oname} | {ty} | {val} | {tgt} | {meas} |")
    L.append("")

    # -- who depends on this --
    consumers: dict[str, list[str]] = {}
    for (cname, local), rr in res.known_refs.items():
        if rr.node == node_name and rr.kind == "output":
            consumers.setdefault(cname, []).append(rr.target.rsplit(".", 1)[1])
    L.append("## Blast radius (who consumes this)")
    L.append("")
    if consumers:
        for cname in sorted(consumers):
            c = doc.nodes.get(cname)
            j = c.judgment.status if isinstance(c, G.Analysis) else "—"
            L.append(f"- `{cname}` reads {', '.join(f'`{o}`' for o in sorted(set(consumers[cname])))}"
                     f" (judgment: {j})")
    else:
        L.append("- no graph consumers (leaf claim)")
    L.append("")

    # -- upstream, one line each --
    ups = sorted({rr.node for (c, _), rr in res.known_refs.items()
                  if c == node_name and rr.kind == "output"})
    if ups:
        L.append("## Upstream (one line each — pack separately to audit)")
        L.append("")
        for u in ups:
            un = doc.nodes.get(u)
            if isinstance(un, G.Analysis):
                model = un.framing.model or un.core.lang
                L.append(f"- `{u}` ({model}; judgment {un.judgment.status}) — `uel pack {u}`")
        L.append("")

    # -- the author's own judgment --
    L.append("## Judgment (the author's, verbatim)")
    L.append("")
    j = an.judgment
    L.append(f"- status: **{j.status}**")
    if j.text:
        L.append(f"- “{j.text}”")
    if j.doubts:
        L.append(f"- doubts: “{j.doubts}”")
    L.append("")

    # -- reproduce & cite --
    L.append("## Reproduce and cite")
    L.append("")
    L.append(f"- `uel build --node {node_name}` re-executes; `uel check` re-verdicts targets/seams")
    if st is not None:
        L.append(f"- recipe `{st.recipe[7:19]}` = def `{str(st.parts.get('def', ''))[7:19]}` "
                 f"+ core `{str(st.parts.get('core', ''))[7:19]}` "
                 f"+ {len(st.parts.get('inputs', {}))} input hashes + tool pins")
    if entry and entry.run:
        L.append(f"- last run {entry.run.get('ts', '?')} ({entry.run.get('wall_s', '?')} s, "
                 f"engine {entry.run.get('engine', 'python')})")
    L.append("")
    return "\n".join(L)

def _fmt_pred_text(p: G.Predicate) -> str:
    unit = f" {p.unit}" if p.unit else ""
    if p.lo is not None and p.hi is not None: return f"[{p.lo:g}, {p.hi:g}{unit}]"
    if p.hi is not None: return f"<= {p.hi:g}{unit}"
    return f">= {p.lo:g}{unit}"

def _lock_out_text(o) -> str:
    v = o.value
    s = f"[{v[0]:g}, {v[1]:g}] {o.unit}" if isinstance(v, list) else f"{v:g} {o.unit}"
    if isinstance(o.unc, dict) and isinstance(o.unc.get("value"), (int, float)):
        s += f" ± {o.unc['value']:g}" + (" (rel)" if o.unc.get("kind") == "rel" else "")
    return s.strip()

_SOURCE_CAP = 120  # lines of python source inlined before truncation
_IFACE_CAP = 60  # lines of an interface manifest inlined before truncation

def _pack_core(an: G.Analysis, root: Path) -> list[str]:
    L: list[str] = []
    if an.core.lang in ("expr", "stub"):
        L.append(f"`core {an.core.lang}` — the formula is the argument, in evidence:")
        L.append("")
        L.append("```text")
        L.extend(an.core.text.splitlines())
        L.append("```")
        return L
    L.append(f"`core python \"{an.core.path}\"` — opaque to the kernel; source and wrapper below.")
    if an.core.tools:
        L.append("")
        L.append("Pinned tools (identity — a different solver is a different artifact): "
                 + ", ".join(f"`{k}` {v}" for k, v in sorted(an.core.tools.items())))
    if an.core.interface:
        L.append("")
        L.append(f"Interface manifest `{an.core.interface.source}`"
                 + (f" (sha256 {an.core.interface.sha256[:12]}…)" if an.core.interface.sha256 else "")
                 + " — the definition of the wrapped module:")
        ip = root / an.core.interface.source
        try:
            ilines = ip.read_text(encoding="utf-8", errors="replace").splitlines()
            L.append("")
            L.append("```")
            L.extend(ilines[:_IFACE_CAP])
            if len(ilines) > _IFACE_CAP:
                L.append(f"… ({len(ilines) - _IFACE_CAP} more lines — the hash above cites the whole file)")
            L.append("```")
        except OSError:
            L.append("  *(declared but not present on disk — treat as unverified)*")
    p = root / an.core.path
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        L.append("")
        L.append(f"*source `{an.core.path}` unreadable — the recipe hash still pins its content*")
        return L
    L.append("")
    L.append("```python")
    L.extend(lines[:_SOURCE_CAP])
    if len(lines) > _SOURCE_CAP:
        L.append(f"# … ({len(lines) - _SOURCE_CAP} more lines — content is hashed; "
                 f"open {an.core.path} to read in full)")
    L.append("```")
    return L

# Instance query (v0.2): `contains X x N` mints addressable slots

def instances(res: Resolution) -> str:
    """Expand the containment tree into instance designators — the addresses
    per-serial calibration overlays and as-built records attach to. A quantity
    is not an identity; `ApertureElement#2` is."""
    doc = res.doc
    comps = doc.components()
    contained = {c.ref for comp in comps.values() for c in comp.contains}
    roots = sorted(n for n, c in comps.items() if n not in contained and not c.realizes)
    lines: list[str] = []
    CAP = 64

    def walk(name: str, prefix: str, depth: int) -> None:
        comp = comps.get(name)
        if comp is None: return
        target = comps.get(name)
        realizer = next((c for c in comps.values() if c.realizes == name), None)
        eff = realizer or target
        for c in (eff.contains or comp.contains):
            short = c.ref.rsplit(".", 1)[-1]
            child = comps.get(c.ref)
            bound = next((r.name for r in comps.values() if r.realizes == c.ref), None)
            for i in range(1, min(c.count, CAP) + 1):
                desig = f"{prefix}{short}#{i}" if c.count > 1 else f"{prefix}{short}"
                mark = f" -> {bound}" if bound else ("" if (child and child.level == "physical") else "  (unbound)")
                lines.append("  " * depth + f"{desig}{mark}")
                walk(c.ref, f"{desig}." if c.count > 1 else prefix, depth + 1)
            if c.count > CAP:
                lines.append("  " * depth + f"… {c.count - CAP} more {short} instances")

    for r in roots:
        lines.append(r)
        walk(r, "", 1)
    if not lines: return "instances: no containment tree in this graph\n"
    lines.append("")
    lines.append("as-built state attaches per designator: `uel calibrate <file> --serial <designator>`")
    return "\n".join(lines) + "\n"

# Provenance query

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
            how = an.core.path or f"{an.core.lang} core, kernel-evaluated"
            lines.append(f"  computed by '{node_name}' ({how}), "
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
        if q is None: return f"provenance: '{target}' does not name a quantity"
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
