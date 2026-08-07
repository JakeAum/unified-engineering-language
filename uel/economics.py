"""The economics scheduler (ADR-0010): what matters, and what to measure next.

The staleness oracle (spec §4.2) answers *what is invalid*; the scheduler runs
it in dependency order (spec §4.3). Neither answers the two questions a
continuously running agent org actually pays for. Inside one iteration the
substrate now costs milliseconds, agent cognition costs minutes-to-hours, and
the physical oracle costs days-to-weeks — so further substrate speedups move
nothing. The two expensive terms are **agent attention** and **oracle
contact**, and the graph already carries everything needed to schedule both:

- **Attention** — of everything stale, where should cognition go first?
  `rank()` scores the non-fresh executables against nine named signals the
  kernel already computes and hands back the contributing terms, so an agent
  reads *why* a node came first, not only that it did.
- **Experiments** — of everything measurable, which measurement buys the most?
  `info_value()` scores candidate measurements by expected envelope tightening
  × the weight of the consumers they feed × margin pressure.

Both are **advice, not authority**: the checker still gates merges and `uel
build` still walks in dependency order. Nothing here can make a red graph
green, and nothing here reorders execution.

Scoring is a weighted sum of terms each normalized to [0, 1]:

    score = Σ_t WEIGHT[t] · value_t          value_t ∈ [0, 1]

Normalization is the point. A raw count (say, "42 downstream nodes") makes the
score unbounded and incomparable between graphs, and lets one term silently
swamp every other; a normalized term means what its weight says it means, in
every project. Ties break toward topological order, so equal-value work is
offered in buildable order, and `frontier` marks the nodes whose upstreams are
all fresh — actionable right now.

The signals, and why each one is on the list (spec sections in parentheses):

- **broken** — the last run failed, or a verification contract the analysis
  declared about itself failed (§8.1, ADR-0008). A broken run is not a result;
  it is loud, cheap signal, and it blocks its whole cone.
- **target** — a declared acceptance bound (ADR-0007) is violated, crosses the
  line inside its own band, or is still pending. Requirement satisfaction is a
  computed property here, so a target verdict is the sharpest statement the
  graph can make about whether work is *finished*.
- **margin** — budget erosion from `conservation.check_budgets` (§7.3): how
  much of the limit the worst-case rollup consumes, escalated when the number
  can only get worse (unvalued leaves in a summed `<=` budget), and maximal
  when the node's own leaf has no value at all, because then the budget has no
  verdict until this node runs.
- **fence** — how close this analysis's own inputs sit to its declared
  envelope (§2.5). A value at 96 % of its fence flips on the next
  perturbation; reserve attention there.
- **serves** — the analysis traces to a requirement through `intent req.*`
  (§3.1). Work with no linked requirement is presumptively dead (program §5.3).
- **cone** — blast radius: the fraction of the executable graph downstream.
  Being wrong here is expensive in proportion.
- **hazard** — the fraction of the framing model's registered hazards that no
  analysis `covers` and this framing does not `waive` (UEL0510, ADR-0009).
  These are the failure modes the chosen physics is structurally blind to.
- **stub** — the core is a placeholder, not an analysis (UEL0807). A design
  standing on stubs says so.
- **age** — how old this node's evidence is relative to the rest of the lock.
  Measured *within the lock*, never against wall-clock: a ranking that changes
  because a day passed is not reproducible, and drift relative to the program
  is the signal that was actually wanted.

Weights are ADR-amendable constants, not magic; the table below is the single
source of truth for both the score and the ADR.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional

from . import graph as G
from .conservation import q_interval_si
from .diagnostics import Bag, span_of
from .envelopes import _pred_si
from .lockfile import Lock, LockOutput
from .resolver import Resolution
from .staleness import StaleReport
from .units import UnitError, parse_unit

@dataclass(frozen=True)
class TermSpec:
    """One scoring signal: a normalized value in [0, 1] and what it is worth."""

    name: str
    weight: float
    doc: str

# ADR-0010 weights. Amend through the decision log, not in place.
TERMS: tuple[TermSpec, ...] = (
    TermSpec("broken", 10.0, "last run or a self-declared verification contract failed"),
    TermSpec("target", 8.0, "a declared acceptance target is violated, band-crossing, or pending"),
    TermSpec("margin", 6.0, "budget erosion of the budgets this node can actually move"),
    TermSpec("fence", 5.0, "this analysis's own inputs sit near its declared envelope"),
    TermSpec("serves", 4.0, "traces to a requirement through intent req.*"),
    TermSpec("cone", 3.0, "blast radius: fraction of the executable graph downstream"),
    TermSpec("hazard", 2.5, "registered model hazards neither covered nor waived"),
    TermSpec("stub", 2.0, "the core is a placeholder, not an analysis"),
    TermSpec("age", 1.0, "evidence age relative to the rest of the lock"),
)
WEIGHT: dict[str, float] = {t.name: t.weight for t in TERMS}

# A summed `<=` budget with unvalued leaves can only rise; score it as if it
# were this much further along. Small enough never to invert a real usage gap,
# large enough to break ties among comparably loaded budgets.
RISING_BUMP = 0.25
# Graded target verdicts. Violated is finished work that failed; a band across
# the line is a reviewer's decision; pending is merely evidence not yet in.
TARGET_VIOLATED, TARGET_BAND, TARGET_PENDING = 1.0, 0.4, 0.15

# The shared primitive: band-vs-fence pressure

def band_pressure(band: tuple[float, float], fence_lo: Optional[float],
                  fence_hi: Optional[float]) -> tuple[float, str]:
    """How much of a fence a band consumes, in [0, 1].

    1.0 when the band reaches or crosses the fence — the next perturbation, or
    one measurement, decides validity. Otherwise 1 − headroom/scale, where
    headroom is the nearest distance from the band to a bounded edge and scale
    is the fence width (two-sided) or the bounded edge's magnitude (one-sided).
    Returns (pressure, note); the note names a crossing.

    An exact-zero lower bound in SI is not a real edge: `root_moment in [0, 260
    N*m]` fences a nonnegative quantity that cannot exit below zero, so only the
    upper edge exerts pressure — a tiny moment is the safest case, not the
    hottest. Affine units sort themselves out, since 0 degC is 273.15 K in SI.
    """
    blo, bhi = band
    if fence_lo is not None and blo < fence_lo - 1e-12:
        return 1.0, "band extends below the fence"
    if fence_hi is not None and bhi > fence_hi + 1e-12:
        return 1.0, "band extends above the fence"
    if fence_lo is not None and abs(fence_lo) <= 1e-30 and fence_hi is not None:
        fence_lo = None  # zero lower bound: nonnegative quantity, one-sided fence
    if fence_lo is not None and fence_hi is not None:
        scale, headroom = fence_hi - fence_lo, min(blo - fence_lo, fence_hi - bhi)
    elif fence_hi is not None:
        scale, headroom = abs(fence_hi), fence_hi - bhi
    elif fence_lo is not None:
        scale, headroom = abs(fence_lo), blo - fence_lo
    else:
        return 0.0, ""
    if scale <= 1e-12:
        return 1.0, "fence has zero width"
    return min(1.0, max(0.0, 1.0 - headroom / scale)), ""

def lock_interval_si(out: Optional[LockOutput]) -> Optional[tuple[float, float]]:
    """SI interval of a locked output, widened by its recorded band. This is the
    value that actually flowed across a seam (ADR-0007) — the v0.1 attention
    port could only see statically declared inputs."""
    if out is None or out.value is None: return None
    try:
        u = parse_unit(out.unit)
    except UnitError:
        return None
    if isinstance(out.value, list):
        if len(out.value) != 2 or not all(isinstance(v, (int, float)) for v in out.value):
            return None
        lo, hi = u.to_si(float(out.value[0])), u.to_si(float(out.value[1]))
        return (min(lo, hi), max(lo, hi))
    if not isinstance(out.value, (int, float)) or isinstance(out.value, bool): return None
    v, half = u.to_si(float(out.value)), 0.0
    if isinstance(out.unc, dict) and isinstance(out.unc.get("value"), (int, float)):
        if out.unc.get("kind") == "abs":
            half = abs(float(out.unc["value"])) * u.factor
        elif out.unc.get("kind") == "rel":
            half = abs(float(out.value)) * abs(float(out.unc["value"])) * u.factor
    return (v - half, v + half)

def _cones(order: list[str], upstream: dict[str, list[str]]) -> tuple[dict, dict]:
    """(descendants, ancestors) closures over the executable dependency graph."""
    down: dict[str, set[str]] = {n: set() for n in order}
    up: dict[str, set[str]] = {n: set(upstream.get(n, ())) for n in order}
    for n in order:
        for u in up[n]:
            down.setdefault(u, set()).add(n)

    def close(seed: dict[str, set[str]], nodes: list[str]) -> dict[str, set[str]]:
        memo: dict[str, set[str]] = {}

        def reach(n: str) -> set[str]:
            if n in memo: return memo[n]
            memo[n] = set()  # cycle guard; the resolver rejects real cycles
            out: set[str] = set()
            for d in seed.get(n, ()):
                out.add(d)
                out |= reach(d)
            memo[n] = out
            return out

        return {n: reach(n) for n in nodes}

    return close(down, order), close(up, order)

# Signals — computed once, shared by the ranking and the measurement query

@dataclass
class TargetVerdict:
    output: str
    verdict: str  # violated | band | pending | met
    text: str

@dataclass
class Signals:
    """Every signal the two queries join, computed once against one lock."""

    res: Resolution
    rep: StaleReport
    lock: Lock
    rollups: dict
    descendants: dict[str, set[str]] = field(default_factory=dict)
    ancestors: dict[str, set[str]] = field(default_factory=dict)
    targets: dict[str, list[TargetVerdict]] = field(default_factory=dict)
    broken: dict[str, list[str]] = field(default_factory=dict)
    hazards: dict[str, tuple[int, int, list[str]]] = field(default_factory=dict)
    budgets_fed: dict[str, list[tuple[str, float, bool, str]]] = field(default_factory=dict)
    leaf_budgets: dict[str, list[tuple[str, float, bool]]] = field(default_factory=dict)
    ages: dict[str, float] = field(default_factory=dict)
    intent_peers: dict[str, list[str]] = field(default_factory=dict)  # req -> analyses serving it

def _target_verdicts(res: Resolution, lock: Lock) -> dict[str, list[TargetVerdict]]:
    """Re-read the acceptance verdicts `contracts.check` publishes as UEL0804/0805,
    as data rather than diagnostics."""
    from .contracts import _bound_si

    out: dict[str, list[TargetVerdict]] = {}
    for name, an in sorted(res.doc.analyses().items()):
        for oname in sorted(an.outputs):
            od = an.outputs[oname]
            if not od.target_op: continue
            bound_si, bound_txt, _src = _bound_si(res, lock, name, oname, od)
            if bound_si is None: continue
            entry = lock.nodes.get(name)
            o = entry.outputs.get(oname) if entry else None
            if o is None or o.value is None or isinstance(o.value, list):
                out.setdefault(name, []).append(TargetVerdict(
                    oname, "pending", f"target {od.target_op} {bound_txt} has no computed value yet"))
                continue
            try:
                u = parse_unit(o.unit)
            except UnitError:
                continue
            v_si, eps = u.to_si(float(o.value)), 1e-9 * max(1.0, abs(bound_si))
            meets = v_si >= bound_si - eps if od.target_op == ">=" else v_si <= bound_si + eps
            iv = lock_interval_si(o)
            crosses = bool(iv) and (
                (iv[0] < bound_si - eps) if od.target_op == ">=" else (iv[1] > bound_si + eps))
            shown = f"{o.value:g} {o.unit}".strip()
            if not meets:
                v, txt = "violated", f"{shown} violates target {od.target_op} {bound_txt}"
            elif crosses:
                v, txt = "band", f"{shown} meets {od.target_op} {bound_txt} on the nominal, band crosses it"
            else:
                v, txt = "met", f"{shown} meets {od.target_op} {bound_txt}"
            out.setdefault(name, []).append(TargetVerdict(oname, v, txt))
    return out

def _broken(res: Resolution, lock: Lock) -> dict[str, list[str]]:
    """Failed runs and failed verification contracts (ADR-0008). Probe contracts
    (monotone/case/converged) record their verdict in the lock at build time;
    `against` is a lock-vs-lock comparison judged here, the same way
    `contracts.check` judges it."""
    from .contracts import _ref_si

    out: dict[str, list[str]] = {}
    for name, an in sorted(res.doc.analyses().items()):
        entry = lock.nodes.get(name)
        if entry is None: continue
        if entry.status == "failed":
            out.setdefault(name, []).append("last run failed")
        for rec in entry.run.get("verify") or []:
            if isinstance(rec, dict) and rec.get("ok") is False:
                out.setdefault(name, []).append(f"contract failed: {rec.get('contract', '?')}")
        for i, gv in enumerate(an.verifies):
            if gv.kind != "against": continue
            o = entry.outputs.get(gv.output)
            mine = None
            if o is not None and not isinstance(o.value, list) and o.value is not None:
                try:
                    mine = parse_unit(o.unit).to_si(float(o.value))
                except UnitError:
                    pass
            theirs, _txt = _ref_si(res, lock, name, i)
            if mine is None or theirs is None: continue
            if gv.tol_unit:
                try:
                    ok = abs(mine - theirs) <= float(gv.tol or 0.0) * parse_unit(gv.tol_unit).factor
                except UnitError:
                    continue
            else:
                ok = abs(mine - theirs) <= float(gv.tol or 0.0) * max(abs(theirs), 1e-30)
            if not ok:
                out.setdefault(name, []).append(
                    f"contract failed: verify {gv.output} against {gv.ref}")
    return out

def _hazard_gaps(res: Resolution) -> dict[str, tuple[int, int, list[str]]]:
    """Per analysis: (uncovered, total, names) of its framing model's hazards —
    the same obligation `contracts.check` raises as UEL0510 (ADR-0009)."""
    analyses = res.doc.analyses()
    covered: set[str] = {c for an in analyses.values() for c in an.framing.covers}
    out: dict[str, tuple[int, int, list[str]]] = {}
    for name, an in sorted(analyses.items()):
        if not an.framing.model: continue
        md = next((n for cand in (an.framing.model, f"lib.models.{an.framing.model}")
                   if isinstance(n := res.doc.nodes.get(cand), G.ModelDef)), None)
        if md is None or not md.hazards: continue
        open_ = sorted(h for h in md.hazards if h not in covered and h not in an.framing.waives)
        out[name] = (len(open_), len(md.hazards), open_)
    return out

def _budget_maps(res: Resolution, rollups: dict, ancestors: dict[str, set[str]],
                 rep: StaleReport) -> tuple[dict, dict]:
    """Join budget rollups (§7.3) to the nodes that can actually move them.

    A budget's number moves when a rollup leaf's mass moves, and a leaf's mass
    moves when the geometry core that produces it re-runs — so pressure attaches
    to that geometry node and everything upstream of it. An analysis that cannot
    change a budget does not inherit its urgency; the cone term already carries
    "many things depend on me".

    Direction matters as much as level. A summed `<=` budget with unvalued
    leaves can only rise, so it is scored as if it were `RISING_BUMP` further
    along; and a budget whose own leaf has no value at all is not merely eroded
    but *indeterminate* — the node that would produce that number decides the
    verdict, which is the most any single piece of work can do, so it scores
    the maximum. (The same rule prices an unvalued leaf in `info_value`.)

    Returns (budgets_fed, leaf_budgets): node -> [(budget, usage, scored, why)]
    and leaf component -> [(budget, usage, unvalued)].
    """
    comps = res.doc.components()
    budgets_fed: dict[str, list[tuple[str, float, float, str]]] = {}
    leaf_budgets: dict[str, list[tuple[str, float, bool]]] = {}
    for (cname, bname), r in sorted(rollups.items()):
        key = f"{cname}.{bname}"
        lo, hi = r["total"]
        limit = r["limit"][1] if r["op"] == "<=" else r["limit"][0]
        if abs(limit) <= 1e-12: continue
        if r["op"] == "<=":
            usage = hi / limit
        else:
            usage = (limit / lo) if abs(lo) > 1e-12 else 1.0
        usage = max(0.0, usage)
        unknown = sorted(set(r["unknown"]))
        rising = bool(unknown) and r["op"] == "<="
        notes = []
        if rising:
            notes.append(f"rising: {len(unknown)} unvalued leaf/leaves not yet counted")
        if lo <= limit < hi:
            notes.append("band straddles the limit")
        for leaf in {p[0] for p in r["parts"]} | set(unknown):
            unvalued = leaf in unknown
            leaf_budgets.setdefault(leaf, []).append((key, usage, unvalued))
            comp = comps.get(leaf)
            geom = comp.geometry if comp else ""
            if not geom or geom not in rep.states: continue
            why = list(notes)
            if unvalued:
                why.insert(0, f"'{leaf}' has no value yet — this node decides the verdict")
            elif rep.states[geom].status != "fresh":
                why.append(f"standing on {geom} ({rep.states[geom].status})")
            scored = 1.0 if unvalued else min(1.0, usage * (1 + RISING_BUMP * rising))
            for feeder in {geom} | ancestors.get(geom, set()):
                budgets_fed.setdefault(feeder, []).append((key, usage, scored, "; ".join(why)))
    return budgets_fed, leaf_budgets

def _ages(lock: Lock, order: list[str]) -> dict[str, float]:
    """Evidence age in [0, 1], normalized across the lock's own run timestamps.
    Never wall-clock: a ranking that moves because a day passed is not
    reproducible, and drift *relative to the program* is the real signal.

    A node that never ran is maximally aged *against the history that exists* —
    but when no history exists at all (nothing in this graph has ever been
    built) there is no drift to measure, and every node scores zero rather than
    every node scoring one. A term that fires on everything ranks nothing."""
    stamps: dict[str, float] = {}
    for name in order:
        entry = lock.nodes.get(name)
        ts = (entry.run.get("ts") if entry else None) or ""
        try:
            stamps[name] = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    if not stamps: return {n: 0.0 for n in order}
    newest, oldest = max(stamps.values()), min(stamps.values())
    span = newest - oldest
    return {n: (1.0 if n not in stamps else
                (0.0 if span <= 0 else (newest - stamps[n]) / span)) for n in order}

def signals(res: Resolution, rep: StaleReport, lock: Lock, rollups: dict | None = None) -> Signals:
    """Compute every signal once. `rollups` comes from `conservation.check_budgets`;
    when omitted it is recomputed against a throwaway diagnostic bag (the caller's
    check run has already reported anything worth reporting)."""
    if rollups is None:
        from .conservation import check_budgets

        rollups = check_budgets(res, lock, Bag())
    desc, anc = _cones(rep.order, {n: st.upstream for n, st in rep.states.items()})
    fed, leaf = _budget_maps(res, rollups, anc, rep)
    peers: dict[str, list[str]] = {}
    for n, a in sorted(res.doc.analyses().items()):
        if a.intent.ref: peers.setdefault(a.intent.ref, []).append(n)
    return Signals(res=res, rep=rep, lock=lock, rollups=rollups, descendants=desc, ancestors=anc,
                   targets=_target_verdicts(res, lock), broken=_broken(res, lock),
                   hazards=_hazard_gaps(res), budgets_fed=fed, leaf_budgets=leaf,
                   ages=_ages(lock, rep.order), intent_peers=peers)

# Attention: value-ordering the stale frontier

@dataclass
class Term:
    name: str
    value: float  # normalized signal in [0, 1]
    why: str

    @property
    def weight(self) -> float:
        return WEIGHT[self.name]

    @property
    def contribution(self) -> float:
        return self.value * self.weight

    def to_obj(self) -> dict:
        return {"term": self.name, "value": round(self.value, 4),
                "weight": self.weight, "contribution": round(self.contribution, 4),
                "why": self.why}

@dataclass
class RankedNode:
    name: str
    score: float
    status: str
    frontier: bool  # every upstream fresh: buildable now
    terms: list[Term]
    cone: int
    blocked: int
    reasons: list[str]

    def to_obj(self) -> dict:
        return {"node": self.name, "score": round(self.score, 3), "status": self.status,
                "frontier": self.frontier, "cone": self.cone, "blocked": self.blocked,
                "terms": [t.to_obj() for t in self.terms], "stale_because": self.reasons}

def _fence_term(sig: Signals, name: str, an: G.Analysis) -> Term:
    """Pressure of this analysis's inputs against its own envelope fences. v0.6
    sees the whole input vector: statics from the resolver, and — new — the
    values actually flowing out of upstream locks (ADR-0007)."""
    preds = an.framing.envelope.predicates
    if not preds: return Term("fence", 0.0, "")
    best, best_why = 0.0, ""
    candidates: list[tuple[str, tuple[float, float], str]] = []
    for local, q in sorted(an.params.items()):
        iv = q_interval_si(q)
        if iv: candidates.append((local, iv, "param"))
    for (consumer, local), rr in sorted(sig.res.known_refs.items()):
        if consumer != name: continue
        if rr.quantity is not None:
            iv = q_interval_si(rr.quantity)
            if iv: candidates.append((local, iv, f"from {rr.target}"))
        elif rr.kind == "output":
            producer = sig.lock.nodes.get(rr.node)
            o = producer.outputs.get(rr.target.rsplit(".", 1)[1]) if producer else None
            iv = lock_interval_si(o)
            if iv: candidates.append((local, iv, f"flowing from {rr.target}"))
    for local, iv, src in candidates:
        pred = preds.get(local)
        p_si = _pred_si(pred) if pred else None
        if p_si is None: continue
        p, note = band_pressure(iv, p_si[0], p_si[1])
        if p > best:
            best, best_why = p, (f"input '{local}' at {p:.0%} of its fence ({src})"
                                 + (f" — {note}" if note else ""))
    return Term("fence", best, best_why)

def _node_terms(sig: Signals, name: str, an: G.Analysis, n_exec: int) -> list[Term]:
    terms: list[Term] = []
    broke = sig.broken.get(name, [])
    terms.append(Term("broken", 1.0 if broke else 0.0, "; ".join(broke)))

    verdicts = sig.targets.get(name, [])
    grade = {"violated": TARGET_VIOLATED, "band": TARGET_BAND, "pending": TARGET_PENDING}
    hottest = max(verdicts, key=lambda v: grade.get(v.verdict, 0.0), default=None)
    terms.append(Term("target", grade.get(hottest.verdict, 0.0) if hottest else 0.0,
                      f"{name}.{hottest.output}: {hottest.text}"
                      if hottest and hottest.verdict != "met" else ""))

    fed = sig.budgets_fed.get(name, [])
    if fed:
        key, usage, scored, why = max(fed, key=lambda b: b[2])
        terms.append(Term("margin", scored, f"feeds budget {key} at {usage:.0%} of its limit"
                          + (f" ({why})" if why else "")))
    else:
        terms.append(Term("margin", 0.0, ""))

    terms.append(_fence_term(sig, name, an))

    serves, why = 0.0, ""
    ref = an.intent.ref
    if ref and isinstance(sig.res.doc.nodes.get(ref), G.Requirement):
        peers = sig.intent_peers.get(ref, [name])
        sole = len(peers) == 1
        serves = 1.0 if sole else 0.75
        why = f"serves {ref}" + (" (sole evidence)" if sole else f" (with {len(peers) - 1} other)")
    terms.append(Term("serves", serves, why))

    cone = sig.descendants.get(name, set())
    blocked = {d for d in cone if sig.rep.states[d].status != "fresh"}
    terms.append(Term("cone", len(cone) / max(1, n_exec - 1),
                      f"blast radius {len(cone)} of {n_exec - 1} downstream"
                      + (f", {len(blocked)} of them not fresh" if blocked else "") if cone else ""))

    open_, total, names = sig.hazards.get(name, (0, 0, []))
    terms.append(Term("hazard", (open_ / total) if total else 0.0,
                      f"{open_} of {total} model hazards unanswered: {', '.join(names)}" if open_ else ""))

    terms.append(Term("stub", 1.0 if an.core.lang == "stub" else 0.0,
                      "core is a stub: outputs are declared nominals, not analysis"
                      if an.core.lang == "stub" else ""))

    age = sig.ages.get(name, 1.0)
    terms.append(Term("age", age, "never built — no evidence at all"
                      if sig.lock.nodes.get(name) is None else
                      (f"evidence is the oldest in the lock" if age >= 1.0 else
                       f"evidence {age:.0%} of the way back through the lock's history")
                      if age > 0 else ""))
    return terms

def rank(res: Resolution, rep: StaleReport, lock: Lock, rollups: dict | None = None,
         sig: Signals | None = None, include_fresh: bool = False) -> list[RankedNode]:
    """Value-order the stale frontier. The scheduler still executes in dependency
    order; this orders *cognition* — which invalid claim to think about first.

    `include_fresh` widens the set to every executable node, so a fresh node
    carrying an open obligation (a violated target, an uncovered hazard, a stub)
    is still visible: those are real work the staleness oracle structurally
    cannot see, because rebuilding will not fix any of them.
    """
    sig = sig or signals(res, rep, lock, rollups)
    analyses = res.doc.analyses()
    topo = {n: i for i, n in enumerate(rep.order)}
    out: list[RankedNode] = []
    for name in rep.order:
        st = rep.states[name]
        if st.status == "fresh" and not include_fresh: continue
        terms = _node_terms(sig, name, analyses[name], len(rep.order))
        score = sum(t.contribution for t in terms)
        if st.status == "fresh" and score <= 0.0: continue
        cone = sig.descendants.get(name, set())
        out.append(RankedNode(
            name, score, st.status,
            all(rep.states[u].status == "fresh" for u in st.upstream),
            sorted([t for t in terms if t.value > 0.0], key=lambda t: (-t.contribution, t.name)),
            len(cone), sum(1 for d in cone if rep.states[d].status != "fresh"), list(st.reasons)))
    out.sort(key=lambda r: (-r.score, topo[r.name]))
    return out

# Information value: which single measurement buys the most

@dataclass
class MeasurementValue:
    target: str
    value: float
    kind: str  # quantity | validation | unvalued
    tightening: float
    tightening_note: str
    consumers: list[str]  # direct consumers
    cone: int  # transitive consumer cone size
    consumer_weight: float  # Σ normalized attention score over the cone
    pressure: float
    pressure_note: str

    def to_obj(self) -> dict:
        return {"target": self.target, "value": round(self.value, 4), "kind": self.kind,
                "tightening": round(self.tightening, 4), "tightening_note": self.tightening_note,
                "consumers": self.consumers, "cone": self.cone,
                "consumer_weight": round(self.consumer_weight, 4),
                "pressure": round(self.pressure, 4), "pressure_note": self.pressure_note}

def _ignorance(q: G.Quantity) -> tuple[float, str]:
    """Relative width of *epistemic* uncertainty — declared ignorance, not the
    operating range. An interval value is a range the quantity legitimately
    spans; only the ± part (and TBD / ± cal) is ignorance a measurement removes.
    Info-value ranks *declared* ignorance; it cannot see the unmodeled (spec §10.6)."""
    if q.value is None: return 1.0, "declared TBD"
    if q.unc.kind == "cal": return 1.0, "calibration-pending (± cal)"
    if q.unc.kind == "rel" and q.unc.value:
        return min(1.0, 2.0 * abs(q.unc.value)), f"± {abs(q.unc.value):.1%}"
    if q.unc.kind == "abs" and q.unc.value:
        mid = (abs(q.value[0] + q.value[1]) / 2.0) if isinstance(q.value, tuple) else abs(q.value)
        if mid <= 1e-12: return 1.0, f"± {q.unc.value:g} about zero"
        return min(1.0, 2.0 * abs(q.unc.value) / mid), f"± {q.unc.value:g} {q.unit}".rstrip()
    return 0.0, "declared exact"

def _lock_quantity(out: Optional[LockOutput]) -> Optional[G.Quantity]:
    if out is None or out.value is None or isinstance(out.value, str): return None
    unc = G.Uncertainty()
    if isinstance(out.unc, dict) and out.unc.get("kind") in ("abs", "rel"):
        unc = G.Uncertainty(out.unc["kind"], out.unc.get("value"))
    return G.Quantity(tuple(out.value) if isinstance(out.value, list) else float(out.value),
                      out.unit, unc)

def _candidates(res: Resolution, lock: Lock,
                sig: Signals) -> list[tuple[str, Optional[G.Quantity], str]]:
    """Everything a test campaign could put a number on: declared quantities and
    port attributes, locked analysis outputs (as validation targets), and — new
    in v0.6 — the *unvalued* leaves of a budget rollup, which carry no quantity
    to be uncertain about and are exactly the holes making a budget
    indeterminate. The v0.1 port could not see them at all."""
    out: list[tuple[str, Optional[G.Quantity], str]] = []
    for name, node in sorted(res.doc.nodes.items()):
        if isinstance(node, (G.Requirement, G.MaterialDef)):
            out += [(f"{name}.{qn}", q, "quantity") for qn, q in sorted(node.quantities.items())]
        elif isinstance(node, G.Component):
            out += [(f"{name}.{qn}", q, "quantity") for qn, q in sorted(node.quantities.items())]
            for pn, port in sorted(node.ports.items()):
                out += [(f"{name}.{pn}.{a}", q, "quantity") for a, q in sorted(port.attrs.items())]
        elif isinstance(node, G.Analysis):
            entry = lock.nodes.get(name)
            for on in sorted(node.outputs):
                q = _lock_quantity(entry.outputs.get(on) if entry else None)
                if q is not None: out.append((f"{name}.outputs.{on}", q, "validation"))
    have = {t for t, _, _ in out}
    for leaf, rows in sorted(sig.leaf_budgets.items()):
        for key, _usage, unvalued in rows:
            qname = key.rsplit(".", 1)[1]
            if unvalued and f"{leaf}.{qname}" not in have:
                out.append((f"{leaf}.{qname}", None, "unvalued"))
                have.add(f"{leaf}.{qname}")
    return out

def info_value(res: Resolution, rep: StaleReport, lock: Lock, rollups: dict | None = None,
               sig: Signals | None = None) -> list[MeasurementValue]:
    """Rank candidate measurements by expected information yield:

        value = tightening × (1 + Σ consumer weight) × (1 + margin pressure)

    - *tightening* is the declared ignorance a measurement removes (spec §8).
    - *consumer weight* is the transitive consumer cone weighted by each
      consumer's own attention score, normalized to the hottest node in the
      graph. This is the v0.6 upgrade over a raw cone count: tightening a band
      that feeds a violated target is worth more than tightening one that feeds
      three nodes nobody is waiting on.
    - *margin pressure* is the largest of the band-vs-fence pressure at a direct
      consumer and the erosion of any budget this quantity is a leaf of. It
      peaks where a measurement *decides* a verdict, which is the most a single
      contact with a slow oracle can do.

    Crude by design (gap analysis §2 move 3): even the crude form beats
    hand-picking campaigns, and the honest name for what it ranks is declared
    ignorance — it cannot price the unmodeled (spec §10.6).
    """
    sig = sig or signals(res, rep, lock, rollups)
    analyses = res.doc.analyses()
    ranked = {r.name: r.score for r in rank(res, rep, lock, sig=sig, include_fresh=True)}
    top = max(ranked.values(), default=0.0)
    consumers_of: dict[str, list[tuple[str, str]]] = {}
    for (consumer, local), rr in sorted(res.known_refs.items()):
        consumers_of.setdefault(rr.target, []).append((consumer, local))

    out: list[MeasurementValue] = []
    for target, q, kind in _candidates(res, lock, sig):
        direct = consumers_of.get(target, [])
        if target.startswith("lib.") and not direct:
            continue  # library values nobody consumes are noise, not candidates
        if q is None:
            tight, note = 1.0, "no declared value: an unvalued leaf of a budget rollup"
        else:
            tight, note = _ignorance(q)
        if tight <= 0.0: continue
        cone: set[str] = set()
        for c, _ in direct:
            cone.add(c)
            cone |= sig.descendants.get(c, set())
        weight = sum(max(0.0, ranked.get(c, 0.0)) / top for c in cone) if top > 0 else 0.0
        pressure, pnote = 0.0, ""
        iv = q_interval_si(q) if q is not None else None
        if iv is not None:
            for c, local in sorted(direct):
                an = analyses.get(c)
                pred = an.framing.envelope.predicates.get(local) if an else None
                p_si = _pred_si(pred) if pred else None
                if p_si is None: continue
                p, _n = band_pressure(iv, p_si[0], p_si[1])
                if p > pressure:
                    pressure, pnote = p, f"{p:.0%} of {c}'s fence on '{local}'"
        node = target.rsplit(".", 1)[0]
        for key, usage, unvalued in sig.leaf_budgets.get(node, []):
            if key.rsplit(".", 1)[1] != target.rsplit(".", 1)[1]: continue
            u = 1.0 if unvalued else min(1.0, usage)
            if u > pressure:
                pressure, pnote = u, (f"budget {key} is indeterminate without it"
                                      if unvalued else f"budget {key} at {usage:.0%}")
        out.append(MeasurementValue(target, tight * (1 + weight) * (1 + pressure), kind, tight,
                                    note, sorted({c for c, _ in direct}), len(cone), weight,
                                    pressure, pnote))
    out.sort(key=lambda m: (-m.value, m.target))
    return out

def elasticity_scale(res: Resolution, lock: Lock, bag: Bag,
                     values: list[MeasurementValue]) -> None:
    """Refine `tightening` with measured elasticities (v0.6 `uel query sensitivity`).

    Declared ignorance is an input-side band; what a downstream consumer inherits
    is that band times the analysis's elasticity e = %Δout/%Δin. A 10 % band on a
    superlinear input is a wider output band than a 10 % band on a dead one, and
    the perturbation machinery already knows which is which. Costs real core runs
    — hence opt-in — and needs a fresh lock to perturb around, so anything
    unmeasurable keeps its structural score.
    """
    from .scheduler import _current_input_si, _node_span, _out_si, _rerun_outputs

    analyses = res.doc.analyses()
    cache: dict[tuple[str, str], float] = {}

    def elasticity(node: str, local: str) -> Optional[float]:
        if (node, local) in cache: return cache[(node, local)]
        an, entry = analyses.get(node), lock.nodes.get(node)
        if an is None or entry is None or entry.status != "fresh" or not entry.outputs: return None
        base = {o: si for o, out in entry.outputs.items()
                if (si := _out_si(out.value, out.unit)) is not None}
        in_si = _current_input_si(res, an, node, lock, local)
        if not base or in_si is None: return None
        delta = 0.05 * abs(in_si) if in_si != 0.0 else 1.0
        outs, _err = _rerun_outputs(res, an, node, lock, bag, _node_span(res, node),
                                    {local: in_si + delta})
        if outs is None: return None
        es = [abs(((outs[o] - base[o]) / abs(base[o])) / (delta / abs(in_si)))
              for o in base if o in outs and base[o] != 0.0 and in_si != 0.0]
        cache[(node, local)] = max(es) if es else 0.0
        return cache[(node, local)]

    binds: dict[str, list[tuple[str, str]]] = {}
    for (consumer, local), rr in sorted(res.known_refs.items()):
        binds.setdefault(rr.target, []).append((consumer, local))
    for m in values:
        es = [e for consumer, local in binds.get(m.target, [])
              if (e := elasticity(consumer, local)) is not None]
        if not es: continue
        gain = max(es)
        m.tightening = min(1.0, m.tightening * gain)
        m.tightening_note += f" × |e| {gain:.2f} (measured)"
        m.value = m.tightening * (1 + m.consumer_weight) * (1 + m.pressure)
    values.sort(key=lambda m: (-m.value, m.target))

# Diagnostics (UEL09xx) — the economics queries' own advisories

def advise(sig: Signals, ranked: list[RankedNode], values: Optional[list[MeasurementValue]],
           bag: Bag) -> None:
    """Conditions the ranking itself discovers. These are advisories on the
    economics queries, not merge-gate checks: `uel check` decides correctness,
    and being unimportant is not an error. `values=None` means the measurement
    side was not computed on this run, which is not the same as finding none."""
    doc = sig.res.doc
    for r in ranked:
        if r.score > 0.0 or r.status == "fresh": continue
        bag.info(
            "UEL0901",
            f"'{r.name}' is {r.status} but scores zero: nothing downstream, no requirement, "
            f"no budget, no fence, no open obligation",
            span_of(doc.nodes.get(r.name)),
            reason="work with no linked failure is presumptively dead (program §5.3); either "
                   "connect it to a requirement or a consumer, or delete it — rebuilding it "
                   "spends oracle time on a claim nobody has asked for",
        )
    if values is None: return
    if not values:
        bag.info(
            "UEL0902",
            "no candidate measurement: every quantity in this graph is declared exact",
            reason="exactness is a claim, not a fact (spec §8); a design that declares no "
                   "ignorance cannot be calibrated, and its envelopes cannot tighten — "
                   "declare bands (± x, ± x %, ± cal) on the values reality actually decides",
        )
    for m in values[:5]:
        if m.pressure < 1.0: continue
        bag.info(
            "UEL0903",
            f"measuring '{m.target}' would decide a verdict: {m.pressure_note}",
            reason="the most a single contact with a slow oracle can buy is a decision "
                   "(gap analysis §2 move 3); a band sitting across a fence or a budget "
                   "limit turns one test into a verdict rather than a refinement",
        )

# Rendering

def render_rank(ranked: list[RankedNode], rep: StaleReport, top: int = 0,
                terms: bool = True) -> str:
    """The work queue, most valuable first, with the arithmetic shown. An agent
    must be able to read *why* a node came first — a rank with no visible terms
    is an oracle, and this project does not ask anyone to trust one."""
    if not rep.order: return "stale: no executable nodes in this graph\n"
    if not ranked:
        return (f"stale --rank: all {len(rep.order)} executable nodes fresh, "
                "no open obligations — nothing to schedule\n")
    shown = ranked[:top] if top else ranked
    L: list[str] = []
    for i, r in enumerate(shown, 1):
        mark = {"fresh": "FRESH", "stale": "STALE", "missing": "MISSING"}.get(r.status, r.status)
        flag = ("· open obligation, rebuilding will not fix it" if r.status == "fresh"
                else "» buildable now" if r.frontier else "… waiting on upstream")
        L.append(f"{i:>3}. {r.name}   score {r.score:.2f}   {mark}   {flag}")
        if terms:
            for t in r.terms:
                L.append(f"       {t.contribution:>5.2f}  {t.name:<7} "
                         f"{t.value:.2f} x {t.weight:g}   {t.why}")
        if r.reasons:
            L.append(f"       stale because: {'; '.join(r.reasons)}")
    L.append("")
    L.append(f"stale --rank: {len(ranked)} node(s) needing work"
             + (f", top {len(shown)} shown" if len(shown) < len(ranked) else "")
             + f"; scoring = {' + '.join(f'{t.weight:g}*{t.name}' for t in TERMS)}")
    L.append("ranking is advice: `uel check` still gates, `uel build` still walks in "
             "dependency order.")
    return "\n".join(L) + "\n"

def render_info_value(values: list[MeasurementValue], target: str = "", top: int = 0) -> str:
    """Which single test to run next, and the arithmetic behind the answer."""
    if target:
        m = next((v for v in values if v.target == target), None)
        if m is None:
            near = [v.target for v in values if target in v.target][:5]
            return (f"info-value: '{target}' is not a candidate measurement"
                    + (f"; did you mean: {', '.join(near)}?" if near else
                       " (declared exact, or consumed by nothing)") + "\n")
        pos = values.index(m) + 1
        L = [f"info-value: {m.target}   value {m.value:.3f}   rank {pos} of {len(values)}", "",
             f"  tightening       {m.tightening:.3f}   {m.tightening_note}",
             f"  consumer weight  {m.consumer_weight:.3f}   over a cone of {m.cone} "
             f"({', '.join(m.consumers) or 'no direct consumer'})",
             f"  margin pressure  {m.pressure:.3f}   {m.pressure_note or 'no fence or budget engaged'}",
             "",
             f"  value = {m.tightening:.3f} x (1 + {m.consumer_weight:.3f}) "
             f"x (1 + {m.pressure:.3f}) = {m.value:.3f}"]
        return "\n".join(L) + "\n"
    if not values:
        return "info-value: no candidate measurements — every quantity is declared exact\n"
    shown = values[:top] if top else values
    w = max(len(m.target) for m in shown)
    L = [f"  {'value':>7}  {'measurement':<{w}}  {'tighten':>7}  {'cone':>5}  "
         f"{'weight':>6}  {'press':>5}  why"]
    for m in shown:
        why = "; ".join(x for x in (m.tightening_note, m.pressure_note) if x)
        L.append(f"  {m.value:>7.3f}  {m.target:<{w}}  {m.tightening:>7.3f}  {m.cone:>5}  "
                 f"{m.consumer_weight:>6.2f}  {m.pressure:>5.2f}  {why}")
    L.append("")
    L.append(f"info-value: {len(values)} candidate measurement(s)"
             + (f", top {len(shown)} shown" if len(shown) < len(values) else "")
             + "; value = tightening x (1 + consumer weight) x (1 + margin pressure)")
    L.append(f"run next: {values[0].target}")
    return "\n".join(L) + "\n"
