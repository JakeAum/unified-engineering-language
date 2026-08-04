"""The staleness oracle (spec §4.2): what does this change invalidate?

Answered by hash comparison alone, in milliseconds, before any physics runs.
A node is:

- **missing** — never built (no lock entry / no recorded outputs);
- **stale** — its recipe hash differs from the lock (with the differing part
  named: definition, core content, a specific input, tool pins), or any node it
  consumes from is itself stale/missing (dirty-through-dependency), or its last
  run failed;
- **fresh** — recipe matches and every upstream is fresh.

Early cutoff is inherent: recipes hash the *quantized values* consumed, so an
upstream re-run that lands within tolerance leaves downstream recipes unmoved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import graph as G
from .diagnostics import Bag, Span
from .hashing import (
    core_content_hash,
    node_identity_obj,
    quantity_value_hash,
    sha_obj,
    tool_pins,
)
from .lockfile import Lock, LockEntry
from .resolver import Resolution


@dataclass
class NodeState:
    name: str
    status: str  # fresh | stale | missing | failed-last-run
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
    return {n: a for n, a in doc.analyses().items() if a.core.path}


def compute(res: Resolution, lock: Lock) -> StaleReport:
    doc = res.doc
    pol = res.project.tolerances
    root = res.project.root
    execs = executable_nodes(doc)

    # producer edges among executables (knowns referencing outputs)
    upstream: dict[str, set[str]] = {n: set() for n in execs}
    for (consumer, local), rr in res.known_refs.items():
        if consumer in execs and rr.kind == "output" and rr.node in execs:
            upstream[consumer].add(rr.node)

    order = _topo(execs.keys(), upstream)
    report = StaleReport(order=order)

    for name in order:
        an = execs[name]
        parts: dict = {
            "def": sha_obj(node_identity_obj(an, pol)),
            "core": core_content_hash(root, an.core),
            "tools": sha_obj(tool_pins()),
            "inputs": {},
        }
        reasons: list[str] = []
        entry: LockEntry | None = lock.nodes.get(name)
        for local in sorted(an.knowns):
            rr = res.known_refs.get((name, local))
            if rr is None:
                parts["inputs"][local] = "unresolved"
                continue
            if rr.kind == "output":
                producer_entry = lock.nodes.get(rr.node)
                out_name = rr.target.rsplit(".", 1)[1]
                out = producer_entry.outputs.get(out_name) if producer_entry else None
                parts["inputs"][local] = out.hash if out else f"pending:{rr.target}"
            else:
                assert rr.quantity is not None
                parts["inputs"][local] = quantity_value_hash(rr.quantity, pol)
        recipe = sha_obj(parts)

        status = "fresh"
        if entry is None or not entry.outputs and entry.status != "failed":
            status = "missing"
            reasons.append("never built")
        elif entry.status == "failed":
            status = "stale"
            reasons.append("last run failed")
        elif entry.recipe != recipe:
            status = "stale"
            old = entry.parts or {}
            if old.get("def") != parts["def"]:
                reasons.append("definition changed (envelope, params, outputs, or framing)")
            if old.get("core") != parts["core"]:
                reasons.append(f"core script changed ({an.core.path})")
            if old.get("tools") != parts["tools"]:
                reasons.append("tool versions changed")
            for local, h in parts["inputs"].items():
                if old.get("inputs", {}).get(local) != h:
                    rr = res.known_refs.get((name, local))
                    reasons.append(f"input '{local}' changed ({rr.target if rr else '?'})")
            if not reasons:
                reasons.append("recipe changed")
        # dirty-through-dependency
        for up in sorted(upstream[name]):
            if report.states[up].status != "fresh":
                if status == "fresh":
                    status = "stale"
                reasons.append(f"upstream '{up}' is {report.states[up].status}")
        report.states[name] = NodeState(name, status, recipe, parts, reasons, sorted(upstream[name]))
    return report


def _topo(nodes, upstream: dict[str, set[str]]) -> list[str]:
    order: list[str] = []
    seen: dict[str, int] = {}

    def visit(n: str) -> None:
        state = seen.get(n, 0)
        if state:
            return
        seen[n] = 1
        for u in sorted(upstream.get(n, ())):
            visit(u)
        seen[n] = 2
        order.append(n)

    for n in sorted(nodes):
        visit(n)
    return order


def report(res: Resolution, bag: Bag) -> StaleReport:
    """Attach staleness advisories to a check run (UEL0701, info severity)."""
    lock = Lock.load(res.project.lock_path, bag)
    rep = compute(res, lock)
    for name in rep.stale():
        st = rep.states[name]
        node = res.doc.nodes.get(name)
        src = getattr(node, "src", "")
        f, _, ln = src.partition(":")
        bag.info(
            "UEL0701",
            f"'{name}' is {st.status}: " + ("; ".join(st.reasons) or "no recorded state"),
            Span(f, int(ln) if ln.isdigit() else 0),
            reason="run `uel build` to re-execute the stale set in dependency order",
        )
    return rep
