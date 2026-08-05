"""Envelope compatibility (spec §2.5): the fence *is* the type.

The composition rule, enforced at every knowns edge from analysis B to producer A:
**A's guarantees must cover B's assumptions**, or compile error *with a stated
reason*. Two layers:

- **Value predicates** (boxes in v0.1): for every variable both fence, B's
  operating interval must be contained in A's validity interval (UEL0501).
  Variables are compared in SI; differing dimensions are their own error
  (UEL0505). Where B's inputs are statically known, they are additionally
  checked against B's *own* fence (spec: "checked at compile time wherever
  inputs are statically known").

- **Structural claims**: B `require X` against A's entailment closure.
  Conflict (closure contains a claim that excludes X, or vice versa) is the
  compile error the spec names — "you modeled this beam as rigid; downstream
  flutter analysis requires elastic modes" (UEL0502, citing both rationales).
  Silence — no producer provides X — is a warning (UEL0503): the taxonomy is
  hand-authored and incomplete by design; declared-but-unchecked beats
  undeclared (Draft 0.1 posture, spec §10.1).

Bindings are checked with the same rule (spec §2.3, §7.2): the physical
realization's envelope (e.g. a datasheet absolute-maximum fence) must cover the
functional requirement's envelope. And a physical component whose temperature
fence exceeds its material's service temperature draws a warning — the
DFM-and-fatigue-together philosophy applied across libraries.
"""

from __future__ import annotations

from typing import Optional

from . import graph as G
from .diagnostics import Bag, Span, span_of
from .lockfile import Lock
from .resolver import Resolution
from .units import D_TEMP, UnitError, parse_unit, type_name

# Claim taxonomy: entailment closure and conflict detection

class Taxonomy:
    def __init__(self, res: Resolution):
        self.defs: dict[str, G.ClaimDef] = {}
        for name, node in res.doc.nodes.items():
            if isinstance(node, G.ClaimDef):
                self.defs[name.removeprefix("lib.claims.")] = node

    def closure(self, claims) -> set[str]:
        out: set[str] = set()
        work = list(claims)
        while work:
            c = work.pop()
            if c in out: continue
            out.add(c)
            d = self.defs.get(c)
            if d:
                work.extend(d.entails)
        return out

    def conflict(self, a: str, b: str) -> bool:
        da, db = self.defs.get(a), self.defs.get(b)
        return bool((da and b in da.excludes) or (db and a in db.excludes))

    def find_conflict(self, closure: set[str], required: str) -> Optional[str]:
        req_closure = self.closure([required])
        for held in sorted(closure):
            for need in sorted(req_closure):
                if self.conflict(held, need): return held
        return None

# Value predicates

def _pred_si(p: G.Predicate) -> Optional[tuple[Optional[float], Optional[float], tuple]]:
    """(lo_si, hi_si, vtype) of a fence — vtype is (dim, level), so a dB fence
    and a plain-ratio fence are different types (ADR-0006)."""
    try:
        u = parse_unit(p.unit)
    except UnitError:
        return None
    lo = u.to_si(p.lo) if p.lo is not None else None
    hi = u.to_si(p.hi) if p.hi is not None else None
    return lo, hi, u.vtype

def _fmt_pred(p: G.Predicate) -> str:
    unit = f" {p.unit}" if p.unit else ""
    if p.lo is not None and p.hi is not None: return f"[{p.lo:g}, {p.hi:g}{unit}]"
    if p.hi is not None: return f"<= {p.hi:g}{unit}"
    return f">= {p.lo:g}{unit}"

def _contained(inner: tuple, outer: tuple) -> tuple[bool, str]:
    ilo, ihi, _ = inner
    olo, ohi, _ = outer
    eps = 1e-12
    if olo is not None and (ilo is None or ilo < olo - abs(olo) * eps - eps):
        return False, "below" if ilo is not None else "unbounded below"
    if ohi is not None and (ihi is None or ihi > ohi + abs(ohi) * eps + eps):
        return False, "above" if ihi is not None else "unbounded above"
    return True, ""

def _check_predicate_cover(
    consumer_name: str, consumer_env: G.Envelope, consumer_span: Span,
    provider_name: str, provider_env: G.Envelope, provider_span: Span,
    bag: Bag, edge_desc: str,
) -> None:
    for var, need in consumer_env.predicates.items():
        have = provider_env.predicates.get(var)
        if have is None: continue
        n_si, h_si = _pred_si(need), _pred_si(have)
        if n_si is None or h_si is None: continue
        if n_si[2] != h_si[2]:
            bag.error(
                "UEL0505",
                f"envelope variable '{var}' is {type_name(*n_si[2])} in '{consumer_name}' "
                f"but {type_name(*h_si[2])} in '{provider_name}'",
                consumer_span,
                related=[(f"fenced here in '{provider_name}'", provider_span)],
            )
            continue
        ok, how = _contained(n_si, h_si)
        if not ok:
            bag.error(
                "UEL0501",
                f"'{consumer_name}' assumes {var} in {_fmt_pred(need)}, but {edge_desc} "
                f"'{provider_name}' guarantees only {var} in {_fmt_pred(have)} — "
                f"the assumed range extends {how} the guaranteed fence",
                consumer_span,
                reason="composition rule (spec §2.5): a guarantee must cover the assumption it feeds; "
                       "outside its envelope the upstream result is not wrong, it is meaningless",
                related=[(f"guarantee declared here", provider_span)],
            )

# The check

def check(res: Resolution, bag: Bag) -> None:
    doc = res.doc
    tax = Taxonomy(res)

    analyses = doc.analyses()

    # -- analysis-to-analysis composition over knowns edges --
    edges: dict[str, set[str]] = {}
    for (consumer, local), rr in res.known_refs.items():
        if consumer in analyses and rr.kind == "output" and rr.node in analyses:
            edges.setdefault(consumer, set()).add(rr.node)

    for consumer_name, producers in sorted(edges.items()):
        consumer = analyses[consumer_name]
        c_env = consumer.framing.envelope
        c_span = span_of(consumer)
        for producer_name in sorted(producers):
            producer = analyses[producer_name]
            _check_predicate_cover(
                consumer_name, c_env, c_span,
                producer_name, producer.framing.envelope, span_of(producer),
                bag, "upstream analysis",
            )
        # structural claims: requires vs each producer's closure
        for req, rationale in sorted(c_env.requires.items()):
            provided_by = []
            for producer_name in sorted(producers):
                producer = analyses[producer_name]
                closure = tax.closure(producer.framing.envelope.claims)
                if req in closure:
                    provided_by.append(producer_name)
                    continue
                conflicting = tax.find_conflict(closure, req)
                if conflicting is not None:
                    held_rationale = None
                    for held, r in producer.framing.envelope.claims.items():
                        if conflicting in tax.closure([held]):
                            held_rationale = (held, r)
                            break
                    rel = [(f"'{producer_name}' assumes "
                            + (f"'{held_rationale[0]}'" + (f" because \"{held_rationale[1]}\"" if held_rationale[1] else "")
                               if held_rationale else f"'{conflicting}'"),
                            span_of(producer))]
                    bag.error(
                        "UEL0502",
                        f"'{consumer_name}' requires '{req}'"
                        + (f" because \"{rationale}\"" if rationale else "")
                        + f", but upstream '{producer_name}' holds '{conflicting}', which excludes it",
                        c_span,
                        reason="structural claims are statements about dropped physics (spec §2.5); "
                               "what one analysis dropped, a downstream one cannot silently need",
                        related=rel,
                    )
                    provided_by.append(producer_name)  # conflict reported; don't double-report silence
            if not provided_by:
                bag.warning(
                    "UEL0503",
                    f"'{consumer_name}' requires '{req}' but no upstream analysis provides it",
                    c_span,
                    reason="declared-but-unchecked beats undeclared (spec §2.5): the need is recorded; "
                           "tighten the upstream framing or accept the unchecked assumption knowingly",
                )

    # -- static inputs vs each analysis's own fence --
    from .conservation import q_interval_si

    for (cname, lname), rr in sorted(res.known_refs.items()):
        consumer = analyses.get(cname)
        if consumer is None or rr.quantity is None: continue
        pred = consumer.framing.envelope.predicates.get(lname)
        if pred is None: continue
        c_span = span_of(consumer)
        iv = q_interval_si(rr.quantity)
        p_si = _pred_si(pred)
        if iv is None or p_si is None: continue
        try:
            qt = parse_unit(rr.quantity.unit).vtype
        except UnitError:
            continue
        if qt != p_si[2]:
            bag.error(
                "UEL0505",
                f"'{cname}': known '{lname}' is {type_name(*qt)} but its envelope fence is {type_name(*p_si[2])}",
                c_span,
            )
            continue
        ok, how = _contained((iv[0], iv[1], qt), p_si)
        if not ok:
            shown = list(rr.quantity.value) if isinstance(rr.quantity.value, tuple) else rr.quantity.value
            bag.error(
                "UEL0501",
                f"'{cname}': input '{lname}' = {shown} {rr.quantity.unit} lies {how} this "
                f"analysis's own validity fence {lname} in {_fmt_pred(pred)}",
                c_span,
                reason="an analysis fed values outside its declared envelope produces numbers, not results (spec §2.5)",
            )

    # -- fences over flowing values: static type agreement (v0.2, ADR-0007) --
    # A fence on a known that references an upstream *output* must be the same
    # quantity type as that output — the v0.1 name-match gap that let a fence
    # silently guard nothing.
    for (cname, lname), rr in sorted(res.known_refs.items()):
        consumer = analyses.get(cname)
        if consumer is None or rr.kind != "output": continue
        pred = consumer.framing.envelope.predicates.get(lname)
        if pred is None: continue
        p_si = _pred_si(pred)
        if p_si is None: continue
        try:
            ot = parse_unit(rr.unit).vtype
        except UnitError:
            continue
        if ot != p_si[2]:
            bag.error(
                "UEL0505",
                f"'{cname}': fence on '{lname}' is {type_name(*p_si[2])}, but the referenced "
                f"output '{rr.target}' is {type_name(*ot)}",
                span_of(consumer),
            )

    # -- binding covers (spec §2.3/§7.2): realization envelope ⊇ functional envelope --
    for comp in doc.components().values():
        if not comp.realizes: continue
        functional = doc.nodes.get(comp.realizes)
        if not isinstance(functional, G.Component): continue
        if functional.envelope.predicates and comp.envelope.predicates:
            _check_predicate_cover(
                functional.name, functional.envelope, span_of(functional),
                comp.name, comp.envelope, span_of(comp),
                bag, "bound realization",
            )

    # -- material service temperature vs component thermal fence --
    for comp in doc.components().values():
        if not comp.material: continue
        mat = doc.nodes.get(comp.material)
        if not isinstance(mat, G.MaterialDef): continue
        service = mat.quantities.get("max_service_temp")
        if service is None or service.value is None or isinstance(service.value, tuple): continue
        try:
            s_si = parse_unit(service.unit).to_si(float(service.value))
        except UnitError:
            continue
        for var, pred in comp.envelope.predicates.items():
            p_si = _pred_si(pred)
            if p_si is None or p_si[2] != (D_TEMP, False) or p_si[1] is None: continue
            if p_si[1] > s_si + 1e-9:
                bag.warning(
                    "UEL0501",
                    f"'{comp.name}' is fenced to {var} up to {pred.hi:g} {pred.unit}, above the service "
                    f"temperature of {comp.material.removeprefix('lib.materials.')} "
                    f"({service.value:g} {service.unit})",
                    span_of(comp),
                    reason="a DFM rule and a materials limit are the same kind of claim: shop and metallurgy knowledge made statically checkable (spec §7.1)",
                )

# Fences vs the values actually flowing (v0.2, ADR-0007)

def check_locked(res: Resolution, bag: Bag, lock: Lock) -> None:
    """Verify every fence on an output-referencing known against the *locked
    value* (nominal ± band) that actually flows across the seam.

    This is the check the v0.1 name-matched envelope comparison could not make:
    the guarantee compared is what the producer computed, not what a
    same-named variable in its framing happened to fence."""
    analyses = res.doc.analyses()
    for (cname, lname), rr in sorted(res.known_refs.items()):
        consumer = analyses.get(cname)
        if consumer is None or rr.kind != "output": continue
        pred = consumer.framing.envelope.predicates.get(lname)
        if pred is None: continue
        p_si = _pred_si(pred)
        if p_si is None: continue
        producer_entry = lock.nodes.get(rr.node)
        out_name = rr.target.rsplit(".", 1)[1]
        out = producer_entry.outputs.get(out_name) if producer_entry else None
        if out is None or out.value is None:
            continue  # staleness already says "never built"; nothing flows yet
        try:
            u = parse_unit(out.unit)
        except UnitError:
            continue
        if u.vtype != p_si[2]:
            continue  # type mismatch already reported statically
        if isinstance(out.value, list):
            lo, hi = u.to_si(float(out.value[0])), u.to_si(float(out.value[1]))
        else:
            v = u.to_si(float(out.value))
            half = 0.0
            if isinstance(out.unc, dict) and isinstance(out.unc.get("value"), (int, float)):
                if out.unc.get("kind") == "abs":
                    half = abs(float(out.unc["value"])) * u.factor
                elif out.unc.get("kind") == "rel":
                    half = abs(float(out.value)) * abs(float(out.unc["value"])) * u.factor
            lo, hi = v - half, v + half
        ok, how = _contained((lo, hi, p_si[2]), p_si)
        if not ok:
            shown = out.value if not isinstance(out.value, list) else list(out.value)
            band = f" (± band [{u.from_si(lo):g}, {u.from_si(hi):g}])" if hi > lo else ""
            bag.error(
                "UEL0806",
                f"'{cname}' fences '{lname}' in {_fmt_pred(pred)}, but the value flowing from "
                f"'{rr.target}' is {shown} {out.unit}{band} — {how} the fence",
                span_of(consumer),
                reason="the fence is checked against the locked value crossing the seam, not a "
                       "name-matched variable (v0.2): rebuild after widening the fence or fixing "
                       "the producer, and say which in the judgment",
                related=[(f"produced by '{rr.node}' here", span_of(res.doc.nodes[rr.node]))]
                if rr.node in res.doc.nodes else [],
            )
