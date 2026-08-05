"""DFM ruleset checking (spec §7.1): shop knowledge, statically checked.
Rules check *feature claims* geometry cores declared about their own shape
(in the lock after a build). Bound rules violated -> UEL0603 with the rule's
recorded rationale; forbid/require check presence; a feature the geometry
never claimed is *pending* (UEL0604) — compile time cannot open the core."""

from __future__ import annotations

from . import graph as G
from .diagnostics import Bag, span_of
from .lockfile import Lock
from .resolver import Resolution
from .units import UnitError, parse_unit

def _feature_si(feat: dict) -> float | None:
    v = feat.get("value")
    if not isinstance(v, (int, float)) or isinstance(v, bool): return None
    try:
        return parse_unit(str(feat.get("unit", ""))).to_si(float(v))
    except UnitError:
        return None

def check(res: Resolution, bag: Bag, lock: Lock) -> None:
    for comp in res.doc.components().values():
        proc = res.doc.nodes.get(comp.process) if comp.process else None
        if not isinstance(proc, G.ProcessDef): continue
        sp = span_of(comp)
        pname = comp.process.removeprefix("lib.process.")
        if not comp.geometry:
            if any(r.op in (">=", "<=", "require") for r in proc.rules.values()):
                bag.info("UEL0604",
                         f"'{comp.name}' binds process '{pname}' but has no geometry; DFM rules unchecked",
                         sp)
            continue
        entry = lock.nodes.get(comp.geometry)
        if entry is None or entry.status != "fresh":
            bag.info("UEL0604",
                     f"'{comp.name}': DFM rules for '{pname}' pending a geometry run "
                     f"('{comp.geometry}' is {'un-built' if entry is None else entry.status})",
                     sp, reason="feature claims come from the geometry core; run `uel build`")
            continue
        for rname, rule in sorted(proc.rules.items()):
            feat = entry.features.get(rule.feature)
            why = f" — {rule.message}" if rule.message else ""
            if rule.op == "forbid":
                if feat is not None and (_feature_si(feat) or 0.0) != 0.0:
                    bag.error("UEL0603",
                              f"'{comp.name}' ({pname}): forbidden feature '{rule.feature}' present "
                              f"(value {feat.get('value')}){why}", sp)
                continue
            if rule.op == "require":
                if feat is None or (_feature_si(feat) or 0.0) == 0.0:
                    bag.error("UEL0603",
                              f"'{comp.name}' ({pname}): required feature '{rule.feature}' absent{why}", sp)
                continue
            if feat is None:
                bag.info("UEL0604",
                         f"'{comp.name}' ({pname}): rule '{rname}' pending — geometry did not declare "
                         f"feature '{rule.feature}'", sp,
                         reason="compile time never opens the core (spec §3.2); a claim the core didn't make cannot be checked")
                continue
            fv = _feature_si(feat)
            if fv is None or rule.limit is None or rule.limit.value is None: continue
            try:
                lu = parse_unit(rule.limit.unit)
            except UnitError:
                continue
            lim = rule.limit.value if not isinstance(rule.limit.value, tuple) else rule.limit.value[1]
            lim_si = lu.to_si(float(lim))
            if (fv < lim_si - 1e-12) if rule.op == ">=" else (fv > lim_si + 1e-12):
                bag.error("UEL0603",
                          f"'{comp.name}' ({pname}): {rule.feature} = {feat.get('value')} {feat.get('unit', '')} "
                          f"violates '{rname}' ({rule.feature} {rule.op} {lim:g} {rule.limit.unit}){why}",
                          sp,
                          reason="DFM rules are data-defined claims of shop knowledge, checked like types (spec §7.1)")
