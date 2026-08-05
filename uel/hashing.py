"""Content addressing (spec §4): tolerance-quantized identity and recipe hashes.
Record fields never hash; every numeric quantity is quantized to the project
grid (else default_rel significant digits) in SI; a core's *content* is identity
(its path is not); tool pins are identity. Quantized identity records the
quantity type (dim + level marker), so `850 mm` == `0.85 m` and `52 dBm` ==
`22 dBW`. Deltas (uncertainties) scale by factor only — offsets cancel."""

from __future__ import annotations

import hashlib
import math
import platform
from pathlib import Path
from typing import Any

from . import EDITION, __version__
from . import graph as G
from .canon import canonical_bytes
from .project import TolerancePolicy
from .units import UnitError, parse_unit

_RECORD_KEYS = ("src", "doc", "conf", "prov", "judgment")

def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()

def sha_obj(obj: Any) -> str:
    return sha(canonical_bytes(obj))

def tool_pins() -> dict:
    return {"python": platform.python_version(), "uel": __version__, "edition": EDITION}

def _sig_round(v: float, rel: float) -> float:
    """Round to ceil(-log10(rel)) significant digits; idempotent."""
    if v == 0.0 or not math.isfinite(v): return 0.0 if v == 0.0 else v
    digits = max(1, round(-math.log10(rel)))
    return float(f"{v:.{digits}e}")

def quantize_si(value_si: float, dim: tuple, pol: TolerancePolicy, level: bool = False) -> float:
    grid = (pol.level_tol if level else pol.abs_tol).get(dim)
    if grid: return round(value_si / grid) * grid
    return _sig_round(value_si, pol.default_rel)

def quantize_in_unit(value: float, unit_text: str, pol: TolerancePolicy) -> float:
    """Quantize a surface value via its SI image (falls back to significant-digit
    rounding on unknown units so hashing never crashes)."""
    try:
        u = parse_unit(unit_text)
    except UnitError:
        return _sig_round(value, pol.default_rel)
    return quantize_si(u.to_si(value), u.dim, pol, u.level)

def quantize_delta_in_unit(value: float, unit_text: str, pol: TolerancePolicy) -> float:
    """Quantize a *difference* (an uncertainty half-width): factor only."""
    try:
        u = parse_unit(unit_text)
    except UnitError:
        return _sig_round(value, pol.default_rel)
    return quantize_si(value * u.factor, u.dim, pol, u.level)

def _strip_and_quantize(obj: Any, pol: TolerancePolicy) -> Any:
    """Drop record keys; quantize quantity- and predicate-shaped dicts into SI."""
    if isinstance(obj, dict):
        out = {}
        unit_text = obj.get("unit", "") if isinstance(obj.get("unit", ""), str) else ""
        is_quantity = "value" in obj or "unc" in obj or "unit" in obj
        is_predicate = ("lo" in obj or "hi" in obj) and not is_quantity
        for k, v in obj.items():
            if k in _RECORD_KEYS: continue
            if k == "text" and obj.get("ref") is not None:
                continue  # intent text is record; intent ref is identity
            if k == "value" and is_quantity:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out[k] = quantize_in_unit(float(v), unit_text, pol)
                elif isinstance(v, list) and len(v) == 2:
                    out[k] = [quantize_in_unit(float(x), unit_text, pol) for x in v]
                else:
                    out[k] = v
            elif k in ("lo", "hi") and is_predicate and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = quantize_in_unit(float(v), unit_text, pol)
            elif k == "unc" and isinstance(v, dict):
                u = dict(v)
                if isinstance(u.get("value"), (int, float)) and not isinstance(u.get("value"), bool):
                    u["value"] = (quantize_delta_in_unit(float(u["value"]), unit_text, pol)
                                  if u.get("kind") == "abs" else _sig_round(float(u["value"]), pol.default_rel))
                out[k] = u
            else:
                out[k] = _strip_and_quantize(v, pol)
        # surface unit text must not affect identity: record the TYPE instead
        if (is_quantity or is_predicate) and unit_text:
            try:
                u = parse_unit(unit_text)
                out["dim"] = (["dB"] if u.level else []) + list(u.dim)
            except UnitError:
                out["dim"] = ["?", unit_text]
            out.pop("unit", None)
        return out
    if isinstance(obj, list): return [_strip_and_quantize(x, pol) for x in obj]
    return obj

def node_identity_obj(node: G.Node, pol: TolerancePolicy) -> Any:
    return _strip_and_quantize(node.to_obj(), pol)

def node_hash(node: G.Node, pol: TolerancePolicy) -> str:
    return sha_obj(node_identity_obj(node, pol))

def quantity_value_hash(q: G.Quantity, pol: TolerancePolicy) -> str:
    return sha_obj(_strip_and_quantize(q.to_obj(), pol))

def output_value_hash(value: Any, unit: str, unc: dict | None, pol: TolerancePolicy) -> str:
    obj: dict = {"value": value, "unit": unit}
    if unc:
        obj["unc"] = unc
    return sha_obj(_strip_and_quantize(obj, pol))

def core_content_hash(project_root: Path, core: G.Core) -> str:
    if core.text:  # expr/stub cores: the canonical body IS the content
        return sha(core.text.encode("utf-8"))
    if not core.path: return "sha256:no-core"
    try:
        return sha((project_root / core.path).read_bytes())
    except OSError:
        return f"missing:{core.path}"

def graph_hash(doc: G.GraphDoc, pol: TolerancePolicy) -> str:
    """Whole-graph identity, stamped onto compiled projections (spec §9.1)."""
    return sha_obj({"nodes": {name: node_hash(n, pol) for name, n in sorted(doc.nodes.items())},
                    "connections": sorted((c.from_ref, c.to_ref) for c in doc.connections),
                    "tools": tool_pins()})
