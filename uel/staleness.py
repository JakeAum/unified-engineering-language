"""The staleness oracle (spec §4.2): what does this change invalidate?
Answered by hash comparison alone, before any physics runs. A node is missing
(never built), stale (recipe differs — with the moved part named — or an
upstream is not fresh, or its last run failed), else fresh. Early cutoff is
inherent: recipes hash the *quantized values* consumed."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import graph as G
from .diagnostics import Bag, span_of
from .hashing import core_content_hash, node_identity_obj, quantity_value_hash, sha_obj, tool_pins
from .lockfile import Lock, LockEntry
from .resolver import Resolution

@dataclass
class NodeState:
    name: str
    status: str  # fresh | stale | missing
    recipe: str
    parts: dict
    reasons: list[str] = field(default_factory=list)
    upstream: list[str] = field(default_factory=list)  # executable producers consumed

@dataclass
class StaleReport:
    states: dict[str, NodeState] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)  # topological order of executables

    def stale(self) -> list[str]:
        return [n for n in self.order if self.states[n].status != "fresh"]

    def fresh(self) -> list[str]:
        return [n for n in self.order if self.states[n].status == "fresh"]

def executable_nodes(doc: G.GraphDoc) -> dict[str, G.Analysis]:
    return {n: a for n, a in doc.analyses().items() if a.core.path or a.core.text}

def compute(res: Resolution, lock: Lock) -> StaleReport:
    pol = res.project.tolerances
    root = res.project.root
    execs = executable_nodes(res.doc)
    upstream: dict[str, set[str]] = {n: set() for n in execs}
    for (consumer, _), rr in res.known_refs.items():
        if consumer in execs and rr.kind == "output" and rr.node in execs:
            upstream[consumer].add(rr.node)
    report = StaleReport(order=_topo(execs.keys(), upstream))
    for name in report.order:
        an = execs[name]
        parts: dict = {"def": sha_obj(node_identity_obj(an, pol)),
                       "core": core_content_hash(root, an.core),
                       "tools": sha_obj(tool_pins()), "inputs": {}}
        for local in sorted(an.knowns):
            rr = res.known_refs.get((name, local))
            if rr is None:
                parts["inputs"][local] = "unresolved"
            elif rr.kind == "output":
                pe = lock.nodes.get(rr.node)
                out = pe.outputs.get(rr.target.rsplit(".", 1)[1]) if pe else None
                parts["inputs"][local] = out.hash if out else f"pending:{rr.target}"
            else:
                assert rr.quantity is not None
                parts["inputs"][local] = quantity_value_hash(rr.quantity, pol)
        recipe = sha_obj(parts)
        entry: LockEntry | None = lock.nodes.get(name)
        status, reasons = "fresh", []
        if entry is None or not entry.outputs and entry.status != "failed":
            status, reasons = "missing", ["never built"]
        elif entry.status == "failed":
            status, reasons = "stale", ["last run failed"]
        elif entry.recipe != recipe:
            status = "stale"
            old = entry.parts or {}
            if old.get("def") != parts["def"]:
                reasons.append("definition changed (envelope, params, outputs, or framing)")
            if old.get("core") != parts["core"]:
                reasons.append(f"core changed ({an.core.path or an.core.lang + ' body'})")
            if old.get("tools") != parts["tools"]:
                reasons.append("tool versions changed")
            for local, h in parts["inputs"].items():
                if old.get("inputs", {}).get(local) != h:
                    rr = res.known_refs.get((name, local))
                    reasons.append(f"input '{local}' changed ({rr.target if rr else '?'})")
            reasons = reasons or ["recipe changed"]
        for up in sorted(upstream[name]):
            if report.states[up].status != "fresh":
                status = "stale" if status == "fresh" else status
                reasons.append(f"upstream '{up}' is {report.states[up].status}")
        report.states[name] = NodeState(name, status, recipe, parts, reasons, sorted(upstream[name]))
    return report

def _topo(nodes, upstream: dict[str, set[str]]) -> list[str]:
    order: list[str] = []
    seen: dict[str, int] = {}

    def visit(n: str) -> None:
        if seen.get(n, 0): return
        seen[n] = 1
        for u in sorted(upstream.get(n, ())):
            visit(u)
        seen[n] = 2
        order.append(n)

    for n in sorted(nodes):
        visit(n)
    return order

def report(res: Resolution, bag: Bag) -> StaleReport:
    """Attach staleness advisories (UEL0701, info) to a check run."""
    rep = compute(res, Lock.load(res.project.lock_path, bag))
    for name in rep.stale():
        st = rep.states[name]
        bag.info("UEL0701",
                 f"'{name}' is {st.status}: " + ("; ".join(st.reasons) or "no recorded state"),
                 span_of(res.doc.nodes.get(name)),
                 reason="run `uel build` to re-execute the stale set in dependency order")
    return rep
