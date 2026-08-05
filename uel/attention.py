"""Attention and information value (ADR-0005): the economics scheduler.

The staleness oracle answers *what is invalid*; the scheduler executes it in
dependency order. Neither answers the two questions a continuously running
agent org actually pays for:

- **Attention** — of everything stale, where should cognition go first?
- **Experiments** — of everything measurable, which measurement buys the most?

Both are computed from data the graph already carries — downstream cones,
declared envelope fences, uncertainty bands, budget rollups — with no new
syntax. The scores are transparent heuristics with named components (the
breakdown ships with every row); sensitivity-aware refinement is v0.2
(spec §4.3 escalation). Weights are ADR-amendable constants, not magic.

Attention score, per non-fresh executable node:

    score = 8·failed_last_run + 4·fence_pressure + 1·blocked_downstream
          + 2·serves_requirement

- *failed last run* first: a failed core is cheap, loud signal and blocks its
  whole cone.  - *fence pressure*: how close the node's statically-known
  inputs sit to its own declared fence (a value at 96 % of fence flips on the
  next perturbation; reserve attention there).  - *blocked downstream*: the
  stale descendants this node is holding up.  - *serves requirement*: intent
  pointing at `req.*` outranks free-floating work.  Ties break toward
  upstream (topological order), so equal-priority work is offered in
  buildable order. `frontier` marks nodes whose upstreams are all fresh —
  actionable now.

Information value, per measurable quantity (component/requirement/material
quantities, port attributes, and locked analysis outputs as validation
targets):

    value = declared_ignorance × (1 + consumers) × (1 + fence_pressure)

- *declared ignorance* is the relative width of the epistemic uncertainty
  (`± x`, `± x%`), 1.0 for `± cal` (calibration-pending) and declared-TBD
  values, 0.0 for values declared exact — info-value ranks *declared*
  ignorance; it cannot see the unmodeled (spec §10.6).  - *consumers* is the
  transitive consumer cone: tightening a band many analyses inherit is worth
  more.  - *fence pressure* peaks when the band straddles a consumer's fence:
  the measurement decides validity, the most a single test can do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import graph as G
from .conservation import q_interval_si
from .envelopes import _pred_si
from .lockfile import Lock
from .resolver import Resolution
from .staleness import StaleReport

# ADR-0005 weights. Amend through the decision log, not in place.
W_FAILED = 8.0
W_PRESSURE = 4.0
W_BLOCKED = 1.0
W_REQUIREMENT = 2.0


# ---------------------------------------------------------------------------
# The shared primitive: band-vs-fence pressure
# ---------------------------------------------------------------------------


def band_pressure(band: tuple[float, float],
                  fence_lo: Optional[float], fence_hi: Optional[float]) -> tuple[float, str]:
    """How much of a fence a band consumes, in [0, 1].

    1.0 when the band reaches or crosses the fence (the next perturbation, or
    one measurement, decides validity). Otherwise 1 − headroom/scale, where
    headroom is the nearest distance from the band to a bounded fence edge and
    scale is the fence width (two-sided) or the bounded edge's magnitude
    (one-sided). Returns (pressure, note); note names a fence crossing.

    An exact-zero lower bound (in SI) is not a real edge: `load in [0, 260
    N*m]` fences a nonnegative quantity that cannot exit below zero, so only
    the upper edge exerts pressure — a tiny load is the safest case, not the
    hottest. Affine units sort themselves out: 0 degC is 273.15 K in SI, so a
    Celsius fence keeps both edges.
    """
    blo, bhi = band
    if fence_lo is not None and blo < fence_lo - 1e-12:
        return 1.0, "band extends below the fence"
    if fence_hi is not None and bhi > fence_hi + 1e-12:
        return 1.0, "band extends above the fence"
    if fence_lo is not None and abs(fence_lo) <= 1e-30 and fence_hi is not None:
        fence_lo = None  # zero lower bound: nonnegative quantity, one-sided fence
    if fence_lo is not None and fence_hi is not None:
        scale = fence_hi - fence_lo
        headroom = min(blo - fence_lo, fence_hi - bhi)
    elif fence_hi is not None:
        scale = abs(fence_hi)
        headroom = fence_hi - bhi
    elif fence_lo is not None:
        scale = abs(fence_lo)
        headroom = blo - fence_lo
    else:
        return 0.0, ""
    if scale <= 1e-12:
        return 1.0, "fence has zero width"
    return min(1.0, max(0.0, 1.0 - headroom / scale)), ""


def _own_fence_pressure(an: G.Analysis, res: Resolution) -> tuple[float, str]:
    """Max pressure of an analysis's statically-known inputs (knowns + params)
    against its own envelope fences. Returns (pressure, variable name)."""
    best, best_var = 0.0, ""
    preds = an.framing.envelope.predicates
    statics: dict[str, G.Quantity] = dict(an.params)
    for (consumer, local), rr in res.known_refs.items():
        if consumer == an.name and rr.quantity is not None:
            statics[local] = rr.quantity
    for local in sorted(statics):
        pred = preds.get(local)
        if pred is None:
            continue
        iv = q_interval_si(statics[local])
        p_si = _pred_si(pred)
        if iv is None or p_si is None:
            continue
        p, _ = band_pressure(iv, p_si[0], p_si[1])
        if p > best:
            best, best_var = p, local
    return best, best_var


# ---------------------------------------------------------------------------
# Attention ranking over the stale frontier
# ---------------------------------------------------------------------------


@dataclass
class RankedNode:
    name: str
    score: float
    status: str
    frontier: bool  # every upstream fresh: buildable now
    blocked_downstream: int
    fence_pressure: float
    pressure_var: str
    serves: str  # requirement ref, "" if none
    failed_last_run: bool
    reasons: list[str] = field(default_factory=list)

    def to_obj(self) -> dict:
        return {
            "node": self.name, "score": round(self.score, 3), "status": self.status,
            "frontier": self.frontier, "blocked_downstream": self.blocked_downstream,
            "fence_pressure": round(self.fence_pressure, 3), "pressure_var": self.pressure_var,
            "serves": self.serves, "failed_last_run": self.failed_last_run,
            "reasons": self.reasons,
        }


def _descendants(order: list[str], upstream: dict[str, list[str]]) -> dict[str, set[str]]:
    down: dict[str, set[str]] = {n: set() for n in order}
    for n, ups in upstream.items():
        for u in ups:
            down.setdefault(u, set()).add(n)
    memo: dict[str, set[str]] = {}

    def reach(n: str) -> set[str]:
        if n in memo:
            return memo[n]
        memo[n] = set()  # cycle guard; resolver rejects real cycles
        out: set[str] = set()
        for d in down.get(n, ()):
            out.add(d)
            out |= reach(d)
        memo[n] = out
        return out

    return {n: reach(n) for n in order}


def rank(res: Resolution, rep: StaleReport, lock: Lock) -> list[RankedNode]:
    """Value-order the non-fresh executables. The scheduler still executes in
    dependency order; this orders *cognition* (which stale claim to think
    about, re-frame, or prioritize first)."""
    analyses = res.doc.analyses()
    upstream = {n: st.upstream for n, st in rep.states.items()}
    desc = _descendants(rep.order, upstream)
    stale_set = set(rep.stale())

    out: list[RankedNode] = []
    topo_index = {n: i for i, n in enumerate(rep.order)}
    for name in rep.order:
        st = rep.states[name]
        if st.status == "fresh":
            continue
        an = analyses[name]
        blocked = len(desc[name] & stale_set)
        pressure, pvar = _own_fence_pressure(an, res)
        entry = lock.nodes.get(name)
        failed = bool(entry and entry.status == "failed")
        serves = ""
        if an.intent.ref and isinstance(res.doc.nodes.get(an.intent.ref), G.Requirement):
            serves = an.intent.ref
        frontier = all(rep.states[u].status == "fresh" for u in st.upstream)
        score = (W_FAILED * failed + W_PRESSURE * pressure
                 + W_BLOCKED * blocked + W_REQUIREMENT * bool(serves))
        reasons = list(st.reasons)
        if failed:
            reasons.append("last run failed: loud, cheap signal; unblocks its cone")
        if pressure >= 0.5 and pvar:
            reasons.append(f"input '{pvar}' at {pressure:.0%} of this analysis's own fence")
        if blocked:
            reasons.append(f"holding up {blocked} stale downstream node{'s' if blocked > 1 else ''}")
        if serves:
            reasons.append(f"serves {serves}")
        out.append(RankedNode(name, score, st.status, frontier, blocked,
                              pressure, pvar, serves, failed, reasons))
    out.sort(key=lambda r: (-r.score, topo_index[r.name]))
    return out


# ---------------------------------------------------------------------------
# Information value of candidate measurements
# ---------------------------------------------------------------------------


@dataclass
class MeasurementValue:
    target: str
    value: float
    ignorance: float
    ignorance_note: str
    consumers: int  # transitive consumer cone
    direct: list[str]
    fence_pressure: float
    pressure_consumer: str  # consumer whose fence the band pressures
    kind: str  # "quantity" | "validation" (analysis output vs lock prediction)

    def to_obj(self) -> dict:
        return {
            "target": self.target, "value": round(self.value, 3), "kind": self.kind,
            "ignorance": round(self.ignorance, 3), "ignorance_note": self.ignorance_note,
            "consumers": self.consumers, "direct": self.direct,
            "fence_pressure": round(self.fence_pressure, 3),
            "pressure_consumer": self.pressure_consumer,
        }


def _ignorance(q: G.Quantity) -> tuple[float, str]:
    """Relative width of *epistemic* uncertainty — declared ignorance, not the
    operating range. An interval value is a range the quantity legitimately
    spans; only the ± part (and TBD/± cal) is ignorance a measurement removes."""
    if q.value is None:
        return 1.0, "declared TBD"
    if q.unc.kind == "cal":
        return 1.0, "calibration-pending (± cal)"
    if q.unc.kind == "rel" and q.unc.value:
        return min(1.0, 2.0 * abs(q.unc.value)), f"± {abs(q.unc.value):.1%}"
    if q.unc.kind == "abs" and q.unc.value:
        mid = (abs(q.value[0] + q.value[1]) / 2.0) if isinstance(q.value, tuple) else abs(q.value)
        if mid <= 1e-12:
            return 1.0, f"± {q.unc.value:g} about zero"
        return min(1.0, 2.0 * abs(q.unc.value) / mid), f"± {q.unc.value:g} {q.unit}".rstrip()
    return 0.0, "declared exact"


def _lock_output_quantity(out) -> Optional[G.Quantity]:
    if out is None or out.value is None:
        return None
    unc = G.Uncertainty()
    if isinstance(out.unc, dict) and out.unc.get("kind") in ("abs", "rel"):
        unc = G.Uncertainty(out.unc["kind"], out.unc.get("value"))
    value = tuple(out.value) if isinstance(out.value, list) else float(out.value)
    return G.Quantity(value, out.unit, unc)


def info_value(res: Resolution, rep: StaleReport, lock: Lock) -> list[MeasurementValue]:
    """Rank candidate measurements by expected information yield. Crude by
    design (ADR-0005): even the crude form beats hand-picking campaigns;
    sensitivity-aware yield is the v0.2 escalation."""
    doc = res.doc
    analyses = doc.analyses()
    upstream = {n: st.upstream for n, st in rep.states.items()}
    desc = _descendants(rep.order, upstream)

    # target -> [(consumer, local)]
    consumers_of: dict[str, list[tuple[str, str]]] = {}
    for (consumer, local), rr in res.known_refs.items():
        consumers_of.setdefault(rr.target, []).append((consumer, local))

    # measurable quantity targets
    candidates: list[tuple[str, G.Quantity, str]] = []
    for name, node in sorted(doc.nodes.items()):
        if isinstance(node, (G.Requirement, G.MaterialDef)):
            for qn, q in sorted(node.quantities.items()):
                candidates.append((f"{name}.{qn}", q, "quantity"))
        elif isinstance(node, G.Component):
            for qn, q in sorted(node.quantities.items()):
                candidates.append((f"{name}.{qn}", q, "quantity"))
            for pn, port in sorted(node.ports.items()):
                for an_, q in sorted(port.attrs.items()):
                    candidates.append((f"{name}.{pn}.{an_}", q, "quantity"))
        elif isinstance(node, G.Analysis):
            entry = lock.nodes.get(name)
            for on in sorted(node.outputs):
                q = _lock_output_quantity(entry.outputs.get(on) if entry else None)
                if q is not None:
                    candidates.append((f"{name}.outputs.{on}", q, "validation"))

    out: list[MeasurementValue] = []
    for target, q, kind in candidates:
        direct = consumers_of.get(target, [])
        # library values nobody consumes are noise, not candidates
        if target.startswith("lib.") and not direct:
            continue
        ign, note = _ignorance(q)
        if ign <= 0.0:
            continue
        cone: set[str] = set()
        for c, _ in direct:
            cone.add(c)
            cone |= desc.get(c, set())
        pressure, pconsumer = 0.0, ""
        iv = q_interval_si(q)
        if iv is not None:
            for c, local in sorted(direct):
                an = analyses.get(c)
                if an is None:
                    continue
                pred = an.framing.envelope.predicates.get(local)
                p_si = _pred_si(pred) if pred else None
                if p_si is None:
                    continue
                p, _ = band_pressure(iv, p_si[0], p_si[1])
                if p > pressure:
                    pressure, pconsumer = p, c
        score = ign * (1 + len(cone)) * (1 + pressure)
        out.append(MeasurementValue(target, score, ign, note, len(cone),
                                    sorted({c for c, _ in direct}), pressure, pconsumer, kind))
    out.sort(key=lambda m: (-m.value, m.target))
    return out


# ---------------------------------------------------------------------------
# The agenda: one surface for a waking agent
# ---------------------------------------------------------------------------


@dataclass
class Agenda:
    errors: int
    warnings: int
    ranked: list[RankedNode]
    measurements: list[MeasurementValue]
    budgets: list[dict]  # tightest first
    discrepancies: list[dict]
    pending_judgments: list[str]
    stubs: list[str]  # unreviewed investigation stubs on disk
    candidate_rules: list[str]  # unreviewed entailment candidates on disk

    def to_obj(self) -> dict:
        return {
            "errors": self.errors, "warnings": self.warnings,
            "stale": [r.to_obj() for r in self.ranked],
            "measure": [m.to_obj() for m in self.measurements],
            "budgets": self.budgets,
            "discrepancies": self.discrepancies,
            "pending_judgments": self.pending_judgments,
            "investigation_stubs": self.stubs,
            "candidate_rules": self.candidate_rules,
        }


def _budget_pressure(rollups: dict) -> list[dict]:
    from .units import UnitError, parse_unit

    rows = []
    for (comp, bname), r in sorted(rollups.items()):
        lo, hi = r["total"]  # SI
        limit = r["limit"][1] if r["op"] == "<=" else r["limit"][0]  # SI
        if abs(limit) <= 1e-12:
            continue
        usage = (hi / limit) if r["op"] == "<=" else (limit / lo if lo else 0.0)
        try:
            conv = parse_unit(r["unit"]).from_si
        except UnitError:
            def conv(x: float) -> float:
                return x
        rows.append({
            "budget": f"{comp}.{bname}", "usage": round(usage, 4), "unit": r["unit"],
            "total": [round(conv(lo), 6), round(conv(hi), 6)],
            "limit": round(conv(limit), 6), "op": r["op"],
            "unknown": sorted(set(r["unknown"])),
        })
    rows.sort(key=lambda r: (-r["usage"], r["budget"]))
    return rows


def _open_discrepancies(res: Resolution, lock: Lock) -> list[dict]:
    from .calibration import load_overlay

    out: list[dict] = []
    targets = load_overlay(res.project.root)
    for target, entries in sorted(targets.items()):
        if not entries:
            continue
        latest = max(entries, key=lambda e: e.get("ts", ""))
        if latest.get("verdict") == "discrepancy" or latest.get("discrepancy"):
            out.append({"target": target, "kind": "as-built departs from as-designed",
                        "source": latest.get("source", ""), "ts": latest.get("ts", "")})
    for name, entry in sorted(lock.nodes.items()):
        for on, v in sorted((entry.run.get("validation") or {}).items()):
            if v.get("verdict") == "outside_envelope":
                out.append({"target": f"{name}.outputs.{on}",
                            "kind": "measurement outside predicted band",
                            "source": v.get("source", ""), "ts": v.get("ts", "")})
    return out


def build_agenda(res: Resolution, rep: StaleReport, lock: Lock,
                 rollups: dict, errors: int, warnings: int) -> Agenda:
    doc = res.doc
    pending = sorted(
        n for n, a in doc.analyses().items()
        if a.akind == "analysis" and a.core.path and a.judgment.status == "pending"
        and not n.startswith("lib.")
    )
    stubs = sorted(
        str(p.relative_to(res.project.root))
        for p in (res.project.root / "analysis" / "investigations").glob("*.uel.suggested")
    ) if (res.project.root / "analysis" / "investigations").is_dir() else []
    rules_dir = res.project.root / "calibration" / "candidate-rules"
    candidate_rules = sorted(
        str(p.relative_to(res.project.root)) for p in rules_dir.glob("*.md")
    ) if rules_dir.is_dir() else []
    return Agenda(
        errors=errors, warnings=warnings,
        ranked=rank(res, rep, lock),
        measurements=info_value(res, rep, lock),
        budgets=_budget_pressure(rollups),
        discrepancies=_open_discrepancies(res, lock),
        pending_judgments=pending,
        stubs=stubs,
        candidate_rules=candidate_rules,
    )


def render_agenda(a: Agenda, top: int = 5) -> str:
    """Human render. The order of sections is the standing work policy
    (docs/org/user-org-loop.md): errors, then stale work, then judgments and
    discrepancies (epistemic debt), then the next measurement, then margins."""
    L: list[str] = []
    if a.errors:
        L.append(f"1. compile errors: {a.errors} — nothing outranks a red check (`uel check`)")
    else:
        L.append("1. compile: clean" + (f" ({a.warnings} warnings)" if a.warnings else ""))
    if a.ranked:
        L.append(f"2. stale work, value order (top {min(top, len(a.ranked))} of {len(a.ranked)}):")
        for r in a.ranked[:top]:
            mark = "»" if r.frontier else "…"  # frontier: buildable now
            bits = [f"score {r.score:g}"]
            if r.failed_last_run:
                bits.append("FAILED last run")
            if r.fence_pressure > 0:
                bits.append(f"fence {r.fence_pressure:.0%}" + (f" ({r.pressure_var})" if r.pressure_var else ""))
            if r.blocked_downstream:
                bits.append(f"blocks {r.blocked_downstream}")
            if r.serves:
                bits.append(r.serves)
            L.append(f"   {mark} {r.name}  [{', '.join(bits)}]")
    else:
        L.append("2. stale work: none — every executable node is fresh")
    if a.pending_judgments:
        L.append(f"3. judgments pending (epistemic debt): {', '.join(a.pending_judgments)}")
    if a.discrepancies:
        L.append(f"4. open discrepancies ({len(a.discrepancies)}):")
        for d in a.discrepancies:
            L.append(f"   ! {d['target']} — {d['kind']} ({d['source']})")
    if a.stubs:
        L.append(f"   unreviewed investigation stubs: {', '.join(a.stubs)}")
    if a.candidate_rules:
        L.append(f"   unreviewed entailment candidates: {', '.join(a.candidate_rules)}"
                 f" — review; accepted ones amend lib.claims through the merge gate")
    if a.measurements:
        m = a.measurements[0]
        L.append(f"5. measure next: {m.target}  [value {m.value:g} = {m.ignorance:g} ignorance"
                 f" ({m.ignorance_note}) × {1 + m.consumers} consumers × {1 + m.fence_pressure:g} fence]")
        for m in a.measurements[1:top]:
            L.append(f"   then: {m.target}  [value {m.value:g}]")
    if a.budgets:
        b = a.budgets[0]
        L.append(f"6. tightest budget: {b['budget']} at {b['usage']:.0%} of {b['limit']:g} {b['unit']}"
                 + (f" (unvalued: {', '.join(b['unknown'])})" if b["unknown"] else ""))
    return "\n".join(L)
