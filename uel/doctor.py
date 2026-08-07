"""`uel doctor` — the checkup: what is wrong with this model, and how much of it
should you believe?

Every other command answers one question well. `check` grades the sources,
`build` runs the stale cone, `stale` names the invalidation, `project status`
renders the verdicts. None of them answers the question an agent (or a reviewer,
or a program manager) actually opens the repository with: *given everything the
graph and the lock already know, what is the state of this design and where is
the belief load-bearing?* Doctor is that one pass, and it is deliberately the
cheap one — it executes no cores, opens no solver, and touches nothing.

**Two axes, not one.** A finding is either **drift** (the model and its recorded
state disagree: stale nodes, violated targets, failed contracts, hand-edited
reports) or **epistemic debt** (the model is internally consistent and still
resting on things nobody checked: opaque cores with no contract, uncertainties
the author typed in by hand, hazards a framing waived with a shrug). Drift is
loud and mechanical. Debt is quiet, compounds, and is the reason a design review
finds in an hour what the compiler could have said in a second.

**The trust ledger** is the second axis made countable. Belief in a computed
number rests on exactly one of three legs (ADR-0008 §Intent):

| leg | what it means | how doctor recognizes it |
|---|---|---|
| by construction | `core expr`: the formula *is* the argument — types inferred before any run, band propagated by interval arithmetic (ADR-0005/0006) | `core.lang == "expr"` |
| by contract | an opaque core interrogated behaviourally: `against` an independent oracle, `monotone`, golden `case`, `converged` (ADR-0008) | `verifies` + the verdicts recorded in `run.verify` |
| on the author's word | `core python` with no contract: the kernel typed the shell and trusted the physics | everything left over |

The ratio between those three is the single most useful number about a model's
credibility, so doctor prints it as a total and not only as a per-node table.

**Asserted vs. propagated uncertainty.** The scheduler hands a Python core every
input's declared band in the payload and accepts whatever `unc` comes back
(`uel/scheduler.py: _payload_quantity` / the `outputs` validation) — it checks
the *unit*, never the *width*. So on an opaque core the ± is authorial
assertion, and the kernel cannot tell a carefully propagated band from a typed-in
one. `examples/apache-one/analysis/spar_static.py` is the honest specimen: it
consumes a `root_moment` declared `± cal` — "unknown but declared, treated as
wide" (uel/graph.py) — and returns `rel 0.05`. That is a fidelity hole, and
UEL1050/1051/1052 make it visible rather than leaving it to a reviewer's eye.

**Self-authenticating.** Every finding cites the hash it was derived from — the
node's recipe, the output's quantized value hash, the model node's content hash,
the projection's stamped graph hash. Those are the same twelve hex characters
`uel hash`, `uel pack`, the projection headers and `uel.lock` already carry, so a
reader can recompute any claim in this report without trusting the report. A
report nobody can check is a report nobody should believe.

**Doctor never files anything, and never repairs anything.** It observes and
prints. Reporting a defect upstream — like fixing one — is an explicit human or
agent decision, never a side effect of having run an audit; CI may run doctor, CI
may not file. That rule is inherited verbatim from the v0.1.3 doctor's decision
record, `0007-doctor-and-upstream-issues.md` §Framing — *"the doctor observes and
writes; it never repairs, never commits, and never files without an explicit
flag"* — cited here as **the never-files rule** rather than by number, because the
v0.6 decision log reuses 0007 for targets and seam values. `--strict` therefore
does exactly one thing: it exits nonzero on error-severity findings, so the
checkup can be a merge-gate step. It still files nothing.

Diagnostic band: UEL10xx (registered in `uel.diagnostics.CODES`; codes are stable
API within an edition and are never renumbered).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import EDITION, __version__
from . import graph as G
from .diagnostics import Bag, CODES, Span, span_of
from .hashing import core_content_hash, graph_hash, node_hash, tool_pins
from .lockfile import Lock, LockEntry
from .resolver import Resolution
from .staleness import compute
from .units import UnitError, parse_unit

SHORT = 12  # hash prefix width — the same one projection stamps and `uel pack` cite

# A waiver is an engineering argument or it is denial (the parser already refuses
# `waive X` with no `because`, uel/parser.py:867). These are the shapes a reason
# takes when someone wanted the diagnostic to go away.
BOILERPLATE = frozenset((
    "n/a", "na", "n a", "none", "no", "nope", "tbd", "todo", "fixme", "later",
    "not applicable", "does not apply", "doesn't apply", "not relevant",
    "out of scope", "not a concern", "not an issue", "not significant",
    "negligible", "small", "minor", "handled elsewhere", "handled",
    "see above", "see below", "see the doc", "known", "understood", "accepted",
    "by inspection", "engineering judgment", "engineering judgement", "ok",
))
MIN_REASON_WORDS = 8

_STAMP = re.compile(r"\bgraph ([0-9a-f]{%d})\b" % SHORT)
_COMPILED_LINE = re.compile(r"^> Compiled .*$", re.M)
_PROJECTION_FILE = re.compile(r"^(bom|icd|work|status)(?:-(.+))?\.md$")


def _h(full: str) -> str:
    """`sha256:abcd…` → the twelve hex characters everything else in the kernel
    cites. Prefixes are enough to grep `uel.lock`, which is the point.

    Non-hashes pass through whole: the staleness oracle records `missing:<path>`
    and `pending:<ref>` in a recipe's parts, and truncating those to twelve
    characters would turn a legible fact into an unverifiable-looking hash."""
    if not full: return "—"
    if not full.startswith("sha256:"): return full
    return full[7:7 + SHORT] or "—"


@dataclass
class Finding:
    """One audited claim. Shaped like `uel.diagnostics.Diagnostic` on purpose —
    stable code, message, `reason` (why the rule exists), span — plus the `cites`
    a reader recomputes to check it."""

    code: str
    severity: str  # error | warning | info
    message: str
    reason: str = ""
    where: Span = field(default_factory=Span)
    cites: list[tuple[str, str]] = field(default_factory=list)  # (label, hash-or-value)

    def __post_init__(self) -> None:
        assert self.code in CODES, f"unregistered diagnostic code {self.code}"
        assert self.severity in ("error", "warning", "info")

    def to_obj(self) -> dict:
        o: dict = {"code": self.code, "title": CODES[self.code], "severity": self.severity,
                   "message": self.message, "span": self.where.to_obj()}
        if self.reason:
            o["reason"] = self.reason
        if self.cites:
            o["cites"] = dict(self.cites)
        return o


@dataclass
class TrustRow:
    """One executable node's place in the ledger."""

    node: str
    lang: str  # expr | python | stub
    basis: str  # construction | contract | word | placeholder
    detail: str  # the contracts and their verdicts, or why there are none
    unc: str  # propagated | asserted | declared | none
    recipe: str  # short hash — the citation for this row
    core: str  # short content hash of the core body/file

    BASIS_TEXT = {
        "construction": "verified by construction",
        "contract": "verified by contract",
        "word": "trusted on the author's word",
        "placeholder": "placeholder (stub)",
    }

    def to_obj(self) -> dict:
        return {"node": self.node, "core": self.lang, "basis": self.basis,
                "detail": self.detail, "uncertainty": self.unc,
                "recipe": self.recipe, "core_hash": self.core}


@dataclass
class Checkup:
    name: str = ""
    root: Path = field(default_factory=Path)
    graph: str = ""  # short graph hash
    edition: str = EDITION
    nodes: int = 0
    lock_nodes: int = 0
    tools: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    ledger: list[TrustRow] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)  # audits actually performed

    def by_severity(self, sev: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == sev]

    def errors(self) -> list[Finding]:
        return self.by_severity("error")

    def totals(self) -> dict[str, int]:
        """The trust ledger's headline. The ratio, not the table, is the number
        worth carrying out of a review."""
        t = {"construction": 0, "contract": 0, "word": 0, "placeholder": 0}
        for row in self.ledger:
            t[row.basis] += 1
        t["total"] = len(self.ledger)
        return t

    def unc_totals(self) -> dict[str, int]:
        t = {"propagated": 0, "asserted": 0, "declared": 0, "none": 0}
        for row in self.ledger:
            t[row.unc] = t.get(row.unc, 0) + 1
        return t

    def to_obj(self) -> dict:
        return {
            "uel_doctor": "1", "project": self.name, "graph": self.graph,
            "edition": self.edition, "nodes": self.nodes, "lock_nodes": self.lock_nodes,
            "tools": self.tools, "checked": self.checked,
            "trust": {"totals": self.totals(), "uncertainty": self.unc_totals(),
                      "ledger": [r.to_obj() for r in self.ledger]},
            "findings": [f.to_obj() for f in self.findings],
            "files_nothing": True,  # the never-files rule: never a side effect of an audit
        }


# ---------------------------------------------------------------------------
# audits
# ---------------------------------------------------------------------------

def _freshness(c: Checkup, res: Resolution, lock: Lock) -> None:
    """Nodes whose recorded state and current recipe disagree (spec §4.2)."""
    c.checked.append("build state (never built / stale / failed)")
    rep = compute(res, lock)
    for name in rep.order:
        st = rep.states[name]
        entry = lock.nodes.get(name)
        sp = span_of(res.doc.nodes.get(name))
        cites = [("recipe now", _h(st.recipe)),
                 ("recipe in lock", _h(entry.recipe) if entry else "—")]
        if entry is not None and entry.status == "failed":
            c.findings.append(Finding(
                "UEL1003", "error",
                f"'{name}' last run FAILED — the lock records no usable result for it",
                "a failed core is not a result; every consumer downstream is reading a "
                "value the kernel already knows is absent or wrong. Fix the core, then "
                "`uel build`", sp, cites))
        elif st.status == "missing":
            c.findings.append(Finding(
                "UEL1001", "warning",
                f"'{name}' has never been built — no recorded outputs",
                "an unbuilt node is a claim nobody has evaluated; anything reading it is "
                "reading a hole (spec §4.2). Run `uel build`", sp, cites))
        elif st.status == "stale":
            c.findings.append(Finding(
                "UEL1002", "warning",
                f"'{name}' is stale: " + ("; ".join(st.reasons) or "recipe changed"),
                "the recorded outputs were computed from a recipe that no longer exists; "
                "the invalidation cone is exact, so `uel build` re-runs only what moved", sp, cites))


def _contract_label(v: G.Verify) -> str:
    """The contract string the scheduler and the checker both write, so a lock
    record can be matched to the declaration that produced it."""
    if v.kind == "monotone":
        return f"verify {v.output} monotone with {v.known} {v.direction}"
    if v.kind == "converged":
        return f"verify converged {v.output} <= {float(v.tol or 0.0):g}"
    if v.kind == "case":
        return f'verify case "{v.path}"'
    return f"verify {v.output} against {v.ref}"


def _out_si(entry: LockEntry | None, oname: str) -> tuple[float | None, str, str]:
    """(SI value, display text, value hash) of a locked output. Intervals,
    artifact paths and unparseable units all read as 'no comparable value' rather
    than raising: the doctor is the command that has to survive a sick project."""
    o = entry.outputs.get(oname) if entry else None
    if o is None: return None, "—", ""
    if not isinstance(o.value, (int, float)) or isinstance(o.value, bool):
        return None, "—", o.hash
    try:
        return parse_unit(o.unit).to_si(float(o.value)), f"{o.value:g} {o.unit}".strip(), o.hash
    except UnitError:
        return None, "—", o.hash


def _contracts(c: Checkup, res: Resolution, lock: Lock) -> dict[str, list[str]]:
    """Verification-contract verdicts (v0.3, ADR-0008), re-derived from the lock
    rather than re-run: failed, pending, and — the one nobody looks for —
    declared-but-never-exercised.

    Returns each node's contract marks, for the trust ledger."""
    c.checked.append("verification contracts (failed / pending / never exercised)")
    from .contracts import _ref_si

    marks: dict[str, list[str]] = {}
    for name, an in sorted(res.doc.analyses().items()):
        if not an.verifies: continue
        sp = span_of(an)
        entry = lock.nodes.get(name)
        records = {str(r.get("contract", "")): r for r in ((entry.run.get("verify") or []) if entry else [])}
        for i, v in enumerate(an.verifies):
            label = _contract_label(v)
            recipe = _h(entry.recipe) if entry else "—"
            if v.kind == "against":
                # lock-vs-lock: judged from recorded values, never from a run
                mine, mine_txt, mine_hash = _out_si(entry, v.output)
                theirs, their_txt = _ref_si(res, lock, name, i)
                cites = [("recipe", recipe), ("output hash", _h(mine_hash))]
                if mine is None or theirs is None:
                    marks.setdefault(name, []).append(f"⏳ {label}")
                    c.findings.append(Finding(
                        "UEL1011", "info",
                        f"{name}: {label} is PENDING — "
                        + ("this output" if mine is None else f"'{v.ref}'")
                        + " has no computed value yet",
                        "a cross-check that has never had two values to compare is a promise, "
                        "not evidence (ADR-0008); `uel build` both sides", sp, cites))
                    continue
                if v.tol_unit:
                    try:
                        tol_si = float(v.tol or 0.0) * parse_unit(v.tol_unit).factor
                    except UnitError:
                        tol_si = 0.0
                    ok, band = abs(mine - theirs) <= tol_si, f"{float(v.tol or 0.0):g} {v.tol_unit}"
                else:
                    tol = float(v.tol or 0.0)
                    ok = abs(mine - theirs) <= tol * max(abs(theirs), 1e-30)
                    band = f"{tol * 100:g} %"
                if ok:
                    marks.setdefault(name, []).append(f"✅ {label}")
                else:
                    marks.setdefault(name, []).append(f"❌ {label}")
                    c.findings.append(Finding(
                        "UEL1010", "error",
                        f"{name}: {label} FAILED — {mine_txt} vs {their_txt}, outside the "
                        f"declared {band} agreement band",
                        "the cross-check oracle is this analysis's declared reason to be "
                        "believed (ADR-0008); one of the two is wrong and the graph cannot "
                        "say which", sp, cites))
                continue

            rec = records.get(label)
            _, _, ohash = _out_si(entry, v.output)
            cites = [("recipe", recipe), ("output hash", _h(ohash))]
            if rec is None:
                marks.setdefault(name, []).append(f"⚠ {label} (never exercised)")
                c.findings.append(Finding(
                    "UEL1012", "warning",
                    f"{name}: {label} is declared but the lock records NO verdict for it — "
                    "the contract has never been exercised",
                    "a contract that has never run is decoration: it reads like evidence in "
                    "review and has produced none. Contracts are part of node identity, so a "
                    "newly added one leaves the node stale until `uel build` grades it", sp, cites))
                continue
            if rec.get("ok"):
                marks.setdefault(name, []).append(f"✅ {label}")
            else:
                marks.setdefault(name, []).append(f"❌ {label}")
                c.findings.append(Finding(
                    "UEL1010", "error",
                    f"{name}: {label} FAILED — {rec.get('detail', 'no detail recorded')}",
                    "a run that breaks its own contract is a failed run, not a result "
                    "(ADR-0008) — the same principle as geometry's mandatory topological "
                    "assertions, generalized", sp, cites))
    return marks


def _targets(c: Checkup, res: Resolution, lock: Lock) -> None:
    """Target verdicts (v0.2, ADR-0007): acceptance as a computed property."""
    c.checked.append("output targets (violated / band-across-the-line / pending)")
    from .contracts import _bound_si

    for name, an in sorted(res.doc.analyses().items()):
        sp = span_of(an)
        entry = lock.nodes.get(name)
        for oname in sorted(an.outputs):
            od = an.outputs[oname]
            if not od.target_op: continue
            bound_si, bound_txt, source = _bound_si(res, lock, name, oname, od)
            if bound_si is None: continue  # unresolvable bound: the resolver already said so
            out = entry.outputs.get(oname) if entry else None
            cites = [("recipe", _h(entry.recipe) if entry else "—"),
                     ("output hash", _h(out.hash) if out else "—")]
            if out is None or not isinstance(out.value, (int, float)) or isinstance(out.value, bool):
                c.findings.append(Finding(
                    "UEL1022", "info",
                    f"target on '{name}.{oname}' ({od.target_op} {bound_txt}) is PENDING — "
                    "no computed value yet",
                    "an acceptance bound with nothing to grade is an intention; `uel build`", sp, cites))
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
            crosses = half > 0.0 and (
                (v_si - half < bound_si - eps) if od.target_op == ">=" else (v_si + half > bound_si + eps))
            if not meets:
                c.findings.append(Finding(
                    "UEL1020", "error",
                    f"'{name}.{oname}' = {out.value:g} {out.unit} VIOLATES its target "
                    f"{od.target_op} {bound_txt} ({source})",
                    "the target is the acceptance line this output exists to satisfy "
                    "(ADR-0007); a violated target is a red gate, not a footnote", sp, cites))
            elif crosses:
                c.findings.append(Finding(
                    "UEL1021", "warning",
                    f"'{name}.{oname}' = {out.value:g} {out.unit} meets its target "
                    f"{od.target_op} {bound_txt} on the nominal, but its ± band crosses the line",
                    "passing-on-the-nominal is the situation a reviewer needs handed to them: "
                    "the declared band already contains the failing case. Tighten the inputs "
                    "or accept the risk in the judgment", sp, cites))


def _normalize_reason(text: str) -> str:
    return re.sub(r"[\s]+", " ", text.strip().strip(" .;:,!-")).lower()


def _hazards(c: Checkup, res: Resolution) -> None:
    """Hazard dispositions (v0.6, ADR-0009): the questions a model cannot ask.

    Coverage is project-granular, matching `uel.contracts`; what doctor adds is
    grading the *waivers*, because a waiver is where a hazard goes to be
    forgotten and nothing else in the kernel reads the prose."""
    c.checked.append("hazard dispositions (uncovered / waived without an argument)")
    analyses = res.doc.analyses()
    if not res.doc.models(): return
    covered_by: dict[str, list[str]] = {}
    for aname in sorted(analyses):
        for cov in analyses[aname].framing.covers:
            covered_by.setdefault(cov, []).append(aname)

    for name in sorted(analyses):
        an = analyses[name]
        sp = span_of(an)
        if not an.framing.model: continue
        md = next((n for cand in (an.framing.model, f"lib.models.{an.framing.model}")
                   if isinstance(n := res.doc.nodes.get(cand), G.ModelDef)), None)
        if md is None: continue
        mh = _h(node_hash(md, res.project.tolerances))
        ah = _h(node_hash(an, res.project.tolerances))
        for hz in sorted(md.hazards):
            cites = [("model hash", mh), ("analysis hash", ah)]
            if hz in covered_by: continue
            if hz not in an.framing.waives:
                c.findings.append(Finding(
                    "UEL1030", "warning",
                    f"'{name}' frames with {an.framing.model}, which cannot see '{hz}' — "
                    f"{md.hazards[hz]}",
                    "a registered model carries the failure modes it is structurally blind to "
                    "(ADR-0009); silence on one is a diagnostic, not an oversight. Answer it: "
                    f"an analysis with `covers {hz}`, or `waive {hz} because \"…\"` here",
                    sp, cites))
                continue
            reason = an.framing.waives[hz]
            norm = _normalize_reason(reason)
            if not norm:
                c.findings.append(Finding(
                    "UEL1031", "error",
                    f"'{name}' waives '{hz}' with an EMPTY reason",
                    "a waiver without a reason is denial with extra steps: it retires the "
                    "diagnostic and records nothing a reviewer can disagree with (ADR-0009)",
                    sp, cites + [("waiver", "\"\"")]))
            elif norm in BOILERPLATE or len(norm.split()) < MIN_REASON_WORDS:
                c.findings.append(Finding(
                    "UEL1031", "warning",
                    f"'{name}' waives '{hz}' with a reason that carries no argument: "
                    f"\"{reason}\"",
                    f"a waiver is the engineering argument for why this blind spot is safe "
                    f"here — it is graded on saying something falsifiable, not on existing "
                    f"(ADR-0009). Flagged because the reason is boilerplate or under "
                    f"{MIN_REASON_WORDS} words; the hazard it retires is: {md.hazards[hz]}",
                    sp, cites + [("waiver", f"{len(norm.split())} words")]))


@dataclass
class Band:
    """A declared uncertainty, read the way a reviewer reads it.

    `rel` is the relative half-width and is `None` whenever that ratio would not
    mean anything — on an affine or level unit the surface value is a position on
    a scale, not a magnitude, so `4 K / 81.7 degC` is arithmetic without physics.
    `unquantified` is `± cal`: declared and *not yet known*, which is a different
    thing from a band of zero (uel/graph.py)."""

    text: str
    rel: float | None = None
    unquantified: bool = False


def _band(value, unit: str, unc: dict | None) -> Band:
    if not isinstance(unc, dict) or unc.get("kind") in (None, "none"): return Band("no band", 0.0)
    if unc.get("kind") == "cal": return Band("± cal (band not yet known)", None, True)
    v = unc.get("value")
    if not isinstance(v, (int, float)): return Band("no band", 0.0)
    v = abs(float(v))
    if unc.get("kind") == "rel": return Band(f"± {v * 100:g} %", v)
    text = f"± {v:g} {unit}".strip()
    try:
        u = parse_unit(unit)
    except UnitError:
        return Band(text)
    if u.affine or u.level: return Band(text)  # a ratio of scale positions is not a ratio
    if not isinstance(value, (int, float)) or not value: return Band(text)
    return Band(text, v / abs(float(value)))


def _input_bands(res: Resolution, name: str, an: G.Analysis,
                 lock: Lock) -> list[tuple[str, Band]]:
    """Every known and param a core consumes, with the band it was handed."""
    out: list[tuple[str, Band]] = []
    for local in sorted(an.knowns):
        rr = res.known_refs.get((name, local))
        if rr is None: continue
        if rr.kind == "output":
            pe = lock.nodes.get(rr.node)
            o = pe.outputs.get(rr.target.rsplit(".", 1)[1]) if pe else None
            if o is None: continue
            b = _band(o.value, o.unit, o.unc if isinstance(o.unc, dict) else None)
        else:
            q = rr.quantity
            if q is None: continue
            b = _band(q.value[1] if isinstance(q.value, tuple) else q.value, q.unit, q.unc.to_obj())
        out.append((f"{local} ({rr.target})", b))
    for pname in sorted(an.params):
        q = an.params[pname]
        out.append((f"{pname} (param)",
                    _band(q.value[1] if isinstance(q.value, tuple) else q.value, q.unit, q.unc.to_obj())))
    return out


def _uncertainty(c: Checkup, res: Resolution, lock: Lock) -> dict[str, str]:
    """Asserted vs. propagated uncertainty.

    `core expr` bands are computed — interval arithmetic over the knowns' declared
    bands, a guaranteed enclosure (ADR-0005). `core python` bands are whatever the
    core printed: the scheduler validates the output's *unit* against the
    declaration and never looks at the width. So on an opaque core the ± is an
    authorial claim about precision, indistinguishable to the kernel from a
    propagated one — and that is worth saying out loud on every output it happens
    to, because downstream fences, targets and rollups are all checked against
    these bands.

    Returns each node's uncertainty basis, for the trust ledger."""
    c.checked.append("uncertainty basis (propagated vs. hand-asserted)")
    basis: dict[str, str] = {}
    for name, an in sorted(res.doc.analyses().items()):
        if not (an.core.path or an.core.text): continue
        entry = lock.nodes.get(name)
        sp = span_of(an)
        core_h = _h(core_content_hash(res.project.root, an.core))
        if an.core.lang == "expr":
            basis[name] = "propagated"
            continue
        if an.core.lang == "stub":
            basis[name] = "declared"
            continue

        basis[name] = "none"
        bands = _input_bands(res, name, an, lock)
        widest, widest_src = 0.0, ""
        unquantified = [nm for nm, b in bands if b.unquantified]
        for nm, b in bands:
            if b.rel is not None and b.rel > widest:
                widest, widest_src = b.rel, f"{nm} {b.text}"
        for oname in sorted(an.outputs):
            od = an.outputs[oname]
            if od.artifact: continue
            o = entry.outputs.get(oname) if entry else None
            if o is None: continue
            cites = [("output hash", _h(o.hash)), ("core content", core_h)]
            if not isinstance(o.unc, dict) or o.unc.get("value") is None:
                if od.unc:
                    basis[name] = "none"
                    c.findings.append(Finding(
                        "UEL1052", "warning",
                        f"'{name}.{oname}' is declared with ± but the lock records no "
                        "uncertainty — the core returned a bare number",
                        "an output declared `±` promises a band; a point value claims a "
                        "precision the model does not have, and every fence, target and "
                        "rollup downstream is checked against the band that isn't there",
                        sp, cites))
                continue
            basis[name] = "asserted"
            out = _band(o.value, o.unit, o.unc)
            c.findings.append(Finding(
                "UEL1050", "info",
                f"'{name}.{oname}' carries an ASSERTED uncertainty {out.text}: the core "
                f"printed it, the kernel neither propagated nor checked it",
                "the core protocol validates an output's unit against its declaration and "
                "never its width (uel/scheduler.py), so on an opaque core the ± is the "
                "author's claim about precision. `core expr` computes the band instead "
                "(ADR-0005); a contract (ADR-0008) is the other way to earn it",
                sp, cites))
            if unquantified:
                c.findings.append(Finding(
                    "UEL1051", "warning",
                    f"'{name}.{oname}' asserts a numeric band {out.text} while its input "
                    f"{unquantified[0]} is declared ± cal — a band the graph says is not "
                    "yet known",
                    "`± cal` means unknown-but-declared, treated as wide (uel/graph.py); a "
                    "result derived from it cannot be known to a hard percentage. Either the "
                    "core is propagating something it was never given, or the input's band "
                    "should come from calibration (`uel calibrate`) before this number is "
                    "believed", sp, cites + [("input", unquantified[0])]))
            elif out.rel is not None and widest > 0.0 and out.rel < widest * (1 - 1e-9):
                c.findings.append(Finding(
                    "UEL1051", "info",
                    f"'{name}.{oname}' asserts {out.text}, relatively narrower than the "
                    f"widest band among this core's inputs ({widest_src}) — worth checking",
                    "an observation, not a verdict, and doctor will not pretend otherwise: "
                    "relative bands compose this way through products and quotients (where a "
                    "result cannot be more precise than its terms) but not through sums, "
                    "where a wide band on a small term stays small. Attribution is also "
                    "node-granular — an opaque core never tells the kernel which inputs feed "
                    "which output. `uel query sensitivity " + name + "` measures the "
                    "elasticities and settles it", sp, cites + [("widest input", widest_src)]))
    return basis


def _trust_ledger(c: Checkup, res: Resolution, lock: Lock,
                  marks: dict[str, list[str]], unc_basis: dict[str, str]) -> None:
    """Where belief is load-bearing (ADR-0008 §Intent). The per-node table exists
    so a claim can be traced; the totals exist because the ratio is the number a
    reviewer should actually leave with."""
    c.checked.append("trust ledger (construction / contract / author's word / stub)")
    for name, an in sorted(res.doc.analyses().items()):
        if not (an.core.path or an.core.text): continue
        entry = lock.nodes.get(name)
        sp = span_of(an)
        recipe = _h(entry.recipe) if entry else "—"
        core_h = _h(core_content_hash(res.project.root, an.core))
        if an.core.lang == "stub":
            basis, detail = "placeholder", "declared nominals, not analysis"
            c.findings.append(Finding(
                "UEL1080", "info",
                f"'{name}' runs a stub core: its outputs are declared nominals, and every "
                "number downstream of it is a placeholder",
                "stubs keep consumers green from minute zero, which is exactly why they are "
                "easy to forget; the maturity ledger names them on every checkup so a design "
                "cannot quietly ship standing on one", sp,
                [("recipe", recipe), ("core content", core_h)]))
        elif an.core.lang == "expr":
            basis = "construction"
            detail = "kernel-evaluated formula, types inferred, band propagated"
            if marks.get(name):
                detail += " · " + "; ".join(marks[name])
        elif marks.get(name):
            basis, detail = "contract", "; ".join(marks[name])
        else:
            basis = "word"
            extra = ""
            if an.akind == "geometry" and entry and entry.assertions:
                extra = f" (asserts {len(entry.assertions)} topological claims — self-reported)"
            detail = f"opaque core, no verification contract{extra}"
            c.findings.append(Finding(
                "UEL1040", "info",
                f"'{name}' is trusted on the author's word: an opaque {an.core.lang} core "
                f"with no verification contract{extra}",
                "the kernel typed the shell of this node — units, references, fences, "
                "staleness — and took the physics inside on faith (ADR-0008). That is a "
                "legitimate position; it is not the same position as a checked one, and the "
                "difference should be visible before someone builds on it. Earn it with "
                "`verify … against` an expr surrogate, `monotone`, or a golden `case`",
                sp, [("recipe", recipe), ("core content", core_h)]))
        c.ledger.append(TrustRow(name, an.core.lang, basis, detail,
                                 unc_basis.get(name, "none"), recipe, core_h))


def _model_hygiene(c: Checkup, res: Resolution, lock: Lock, rollups: dict) -> None:
    """Holes the graph can see in itself: rollups standing on unvalued leaves and
    inputs nothing feeds."""
    c.checked.append("rollup leaves and dangling ports")
    pol = res.project.tolerances
    for (comp_name, bname), r in sorted(rollups.items()):
        unknown = sorted(set(r.get("unknown") or []))
        if not unknown: continue
        comp = res.doc.nodes.get(comp_name)
        c.findings.append(Finding(
            "UEL1070", "warning",
            f"budget '{comp_name}.{bname}' rolls up over {len(unknown)} leaf component(s) "
            f"with no value: {', '.join(unknown)}",
            "a rollup that silently skips its unvalued leaves reports a total that is "
            "guaranteed low; the margin it shows is not the margin you have (spec §7.3)",
            span_of(comp),
            [("component hash", _h(node_hash(comp, pol)) if comp else "—")]))

    from .conservation import _domain_def

    connected: set[tuple[str, str]] = set()
    for conn in res.doc.connections:
        for ref in (conn.from_ref, conn.to_ref):
            head, _, tail = ref.partition(".")
            if tail:
                connected.add((head, tail))
    for comp in sorted(res.doc.components().values(), key=lambda x: x.name):
        for pname in sorted(comp.ports):
            port = comp.ports[pname]
            if port.dir != "in" or (comp.name, pname) in connected: continue
            dom = _domain_def(res, port.domain)
            if dom is not None and dom.dclass == "data": continue
            c.findings.append(Finding(
                "UEL1071", "warning",
                f"'in' port '{comp.name}.{pname}' ({port.domain}) is never connected",
                "an unconnected input is either dead (cut it) or a hole in the model "
                "(connect it); either way the conservation checks over that net are grading "
                "an incomplete picture", span_of(comp),
                [("component hash", _h(node_hash(comp, pol)))]))


def _projections(c: Checkup, res: Resolution, lock: Lock, rollups: dict) -> None:
    """Compiled reports vs. the graph they claim to come from (spec §1.4, §9.1).

    Two diseases that look alike and are not: a **stale** report is honest and out
    of date; a **hand-edited** one still claims its graph hash while its body no
    longer follows from it. The test is exact and needs no seal: a projection is a
    pure function of (graph, lock), so if the header's stamped graph hash matches
    the current one, the body must re-render byte-identically — everything except
    the compile timestamp, which is the only nondeterminism in the renderer."""
    outdir = res.project.root / "out"
    if not outdir.is_dir(): return
    files = sorted(p for p in outdir.glob("*.md") if _PROJECTION_FILE.match(p.name))
    if not files: return
    c.checked.append(f"projection integrity ({len(files)} compiled reports in out/)")

    from . import projections as P

    current = graph_hash(res.doc, res.project.tolerances)
    renderers = {"bom": lambda: P.bom(res, lock, rollups), "icd": lambda: P.icd(res, lock),
                 "work": lambda: P.work_instructions(res, lock),
                 "status": lambda: P.status(res, lock)}
    for p in files:
        m = _PROJECTION_FILE.match(p.name)
        assert m is not None
        kind, serial = m.group(1), m.group(2) or ""
        rel = str(p.relative_to(res.project.root))
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        stamp = _STAMP.search(text)
        claimed = stamp.group(1) if stamp else ""
        cites = [("graph claimed by report", claimed or "none"), ("graph now", _h(current))]
        if not claimed:
            c.findings.append(Finding(
                "UEL1060", "warning",
                f"{rel} carries no graph stamp — it did not come out of `uel project`",
                "every compiled projection is stamped with the graph hash it was compiled "
                "from (spec §9.1); an unstamped document in out/ is an authored artifact "
                "wearing a compiled one's clothes, and nothing can tell you when it went "
                "out of date", Span(rel), cites))
            continue
        if claimed != _h(current):
            c.findings.append(Finding(
                "UEL1060", "warning",
                f"{rel} is STALE: compiled from graph {claimed}, the model is now "
                f"{_h(current)}",
                "the document and the model disagree and the document does not know it — "
                "the drift failure mode in its purest form (spec §1.4). Re-run "
                "`uel project`. Note the graph hash also moves when the kernel or Python "
                "version does: tool pins are identity (spec §4.3)", Span(rel), cites))
            continue
        if serial:
            continue  # an as-built overlay view; re-rendering it needs its own resolution
        try:
            want = _COMPILED_LINE.sub("", renderers[kind]())
        except Exception:
            continue  # cannot re-render, so cannot prove anything: accuse nobody
        got = _COMPILED_LINE.sub("", text)
        if got != want:
            c.findings.append(Finding(
                "UEL1061", "error",
                f"{rel} was HAND-EDITED after compilation: it still claims graph {claimed}, "
                "but its body is not what that graph compiles to",
                "spec §1.4 prohibits hand-editing a compiled artifact by construction, and "
                "this is the construction: a projection is a pure function of (graph, lock), "
                "so a body that does not re-render is a body someone changed. Fix the model "
                "and re-compile — do not regenerate the evidence away before understanding "
                "what the edit was trying to say. Verify: `uel project " + kind +
                " <project> -o /tmp/x` and diff", Span(rel),
                cites + [("body differs from", f"canonical render of graph {claimed}")]))


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------

def run(path: str | Path) -> tuple[Checkup, Bag]:
    """One checkup pass. Executes nothing, writes nothing, files nothing."""
    from .calibration import apply_overlays
    from .checker import run_checks
    from .project import load_project
    from .resolver import resolve_project

    bag = Bag()
    c = Checkup(root=Path(path))
    project = load_project(path, bag)
    c.name, c.root = project.name, project.root
    if bag.errors:
        return c, bag
    res = resolve_project(project, bag)
    if res is None or bag.errors:
        return c, bag
    apply_overlays(res, "")

    # The checker's own diagnostics are `uel check`'s job, not doctor's — but a
    # lock that will not parse is doctor's job, because every verdict below is
    # read out of it and silently auditing an empty one would report a healthy,
    # entirely unbuilt project.
    lock_bag = Bag()  # kept separate: run_checks loads the lock again, and one
    lock = Lock.load(project.lock_path, lock_bag)  # broken lock is one finding
    rollups = run_checks(res, Bag(), lock=False) or {}
    for d in lock_bag.items:
        if d.code == "UEL0003":
            c.findings.append(Finding(
                "UEL1000", "error", f"uel.lock is unreadable: {d.message}",
                "every verdict in this report is read out of the lock; with no lock there "
                "is nothing to audit and an empty one would report a healthy project that "
                "has simply never been built. Restore it from version control, or delete "
                "it and `uel build`", Span("uel.lock")))

    c.graph = _h(graph_hash(res.doc, project.tolerances))
    c.edition = res.doc.edition
    c.nodes = len(res.doc.nodes)
    c.lock_nodes = len(lock.nodes)
    c.tools = tool_pins()

    _freshness(c, res, lock)
    marks = _contracts(c, res, lock)
    _targets(c, res, lock)
    _hazards(c, res)
    unc_basis = _uncertainty(c, res, lock)
    _trust_ledger(c, res, lock, marks, unc_basis)
    _model_hygiene(c, res, lock, rollups)
    _projections(c, res, lock, rollups)

    rank = {"error": 0, "warning": 1, "info": 2}
    c.findings.sort(key=lambda f: (rank[f.severity], f.code, f.where.file, f.where.line, f.message))
    return c, bag


def render(c: Checkup) -> str:
    L: list[str] = []
    L.append(f"uel doctor — {c.name}  ({c.root})")
    L.append(f"  graph {c.graph} · edition {c.edition} · {c.nodes} nodes · "
             f"{c.lock_nodes} lock entries")
    L.append(f"  uel {c.tools.get('uel', __version__)} · python {c.tools.get('python', '?')} "
             "(tool pins are identity: they enter every hash)")
    L.append("")
    L.append("  Every claim below cites the hash it was derived from. Recipe, core-content and")
    L.append("  output hashes are in uel.lock; node hashes recompute with `uel hash --node "
             "<name>`;")
    L.append("  the graph hash with `uel hash`. Check this report; do not take it on trust.")
    L.append("")

    t, u = c.totals(), c.unc_totals()
    if t["total"]:
        L.append("TRUST LEDGER — where belief is load-bearing (ADR-0008)")
        L.append("")
        w = max(len(r.node) for r in c.ledger)
        L.append(f"  {'node'.ljust(w)}  {'core':<7} {'recipe':<13} {'±':<11} basis")
        for r in c.ledger:
            L.append(f"  {r.node.ljust(w)}  {r.lang:<7} {r.recipe:<13} {r.unc:<11} "
                     f"{TrustRow.BASIS_TEXT[r.basis]} — {r.detail}")
        L.append("")
        n = t["total"]
        pct = lambda k: f"{t[k]} ({t[k] * 100 // n}%)"
        L.append(f"  {n} executable nodes: {pct('construction')} verified by construction, "
                 f"{pct('contract')} verified by contract,")
        L.append(f"  {pct('word')} trusted on the author's word, {pct('placeholder')} placeholder stubs.")
        L.append(f"  uncertainty: {u['propagated']} propagated, {u['asserted']} hand-asserted, "
                 f"{u['declared']} declared by a stub, {u['none']} none recorded.")
        L.append("")

    if c.findings:
        L.append("FINDINGS")
        L.append("")
        for f in c.findings:
            L.append(f"  {f.severity} [{f.code}] {f.message}")
            L.append(f"    --> {f.where}")
            if f.reason:
                L.append(f"    reason: {f.reason}")
            if f.cites:
                L.append("    cite: " + " · ".join(f"{k} {v}" for k, v in f.cites))
            L.append("")

    L.append("CHECKED — " + "; ".join(c.checked) if c.checked else "CHECKED — nothing")
    counts = {s: len(c.by_severity(s)) for s in ("error", "warning", "info")}
    L.append("")
    L.append(f"doctor: {len(c.findings)} findings — {counts['error']} errors, "
             f"{counts['warning']} warnings, {counts['info']} info. "
             "Nothing was filed, changed, or built — reporting upstream is a decision, "
             "not a side effect of an audit.")
    return "\n".join(L)


def to_json(c: Checkup) -> str:
    return json.dumps(c.to_obj(), indent=2, ensure_ascii=False)
