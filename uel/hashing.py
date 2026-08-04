"""Content addressing (spec §4): tolerance-quantized identity and recipe hashes.

Identity-for-staleness is a SHA-256 over a node's canonical *identity* content:

- record fields never hash (src/doc/provenance/judgment/confidence/intent text) —
  moving a declaration or writing judgment must not invalidate physics;
- every numeric quantity is **quantized** before hashing: to the project's absolute
  grid for its dimension when one is declared, else to `default_rel` significant
  precision (spec §4.3 draft rule; solver nondeterminism is handled by pinned
  seeds, escalation to sensitivity-aware staleness is v0.2);
- a core file's *content* is identity; its path is not;
- tool pins (python/uel/edition) are identity, as in Nix — a different kernel is a
  different artifact.

The recipe hash of an executable node covers its identity content, the quantized
values it consumes (static graph values directly; upstream outputs via the lock's
recorded output hashes), its core content, and the tool pins — with a per-part
breakdown so staleness can *name* what moved.
"""

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
from .units import DIMENSIONLESS, UnitError, parse_unit

_RECORD_KEYS = ("src", "doc", "conf", "prov", "judgment")


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha_obj(obj: Any) -> str:
    return sha(canonical_bytes(obj))


def tool_pins() -> dict:
    return {
        "python": platform.python_version(),
        "uel": __version__,
        "edition": EDITION,
    }


# ---------------------------------------------------------------------------
# Quantization
# ---------------------------------------------------------------------------


def _sig_round(v: float, rel: float) -> float:
    """Round to ceil(-log10(rel)) significant digits; idempotent."""
    if v == 0.0 or not math.isfinite(v):
        return 0.0 if v == 0.0 else v
    digits = max(1, round(-math.log10(rel)))
    return float(f"{v:.{digits}e}")


def quantize_si(value_si: float, dim: tuple, pol: TolerancePolicy) -> float:
    grid = pol.abs_tol.get(dim)
    if grid:
        return round(value_si / grid) * grid
    return _sig_round(value_si, pol.default_rel)


def quantize_in_unit(value: float, unit_text: str, pol: TolerancePolicy) -> float:
    """Quantize a surface value via its SI image; returns the quantized SI value.

    Hashing always works in SI so that `850 mm` and `85 cm` are the same content.
    Unknown units (already diagnosed elsewhere) fall back to raw significant-digit
    rounding so hashing never crashes.
    """
    try:
        u = parse_unit(unit_text)
    except UnitError:
        return _sig_round(value, pol.default_rel)
    return quantize_si(u.to_si(value), u.dim, pol)


def _q_value(raw: Any, unit_text: str, pol: TolerancePolicy) -> Any:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return quantize_in_unit(float(raw), unit_text, pol)
    if isinstance(raw, list) and len(raw) == 2:
        return [quantize_in_unit(float(raw[0]), unit_text, pol),
                quantize_in_unit(float(raw[1]), unit_text, pol)]
    return raw


def _strip_and_quantize(obj: Any, pol: TolerancePolicy) -> Any:
    """Drop record keys; quantize quantity- and predicate-shaped dicts into SI."""
    if isinstance(obj, dict):
        out = {}
        unit_text = obj.get("unit", "") if isinstance(obj.get("unit", ""), str) else ""
        is_quantity = "value" in obj or "unc" in obj or "unit" in obj
        is_predicate = ("lo" in obj or "hi" in obj) and not is_quantity
        for k, v in obj.items():
            if k in _RECORD_KEYS:
                continue
            if k == "text" and obj.get("ref") is not None:
                continue  # intent text is record; intent ref is identity
            if k == "value" and is_quantity:
                out[k] = _q_value(v, unit_text, pol)
            elif k in ("lo", "hi") and is_predicate and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = quantize_in_unit(float(v), unit_text, pol)
            elif k == "unc" and isinstance(v, dict):
                u = dict(v)
                if isinstance(u.get("value"), (int, float)) and not isinstance(u.get("value"), bool):
                    if u.get("kind") == "abs":
                        u["value"] = quantize_in_unit(float(u["value"]), unit_text, pol)
                    else:
                        u["value"] = _sig_round(float(u["value"]), pol.default_rel)
                out[k] = u
            else:
                out[k] = _strip_and_quantize(v, pol)
        # once quantized into SI, the surface unit text must not affect identity —
        # record the dimension instead so `850 mm` == `0.85 m` and unit renames
        # (same dimension) don't invalidate.
        if is_quantity and unit_text:
            try:
                out["dim"] = list(parse_unit(unit_text).dim)
            except UnitError:
                out["dim"] = ["?", unit_text]
            out.pop("unit", None)
        if is_predicate and unit_text:
            try:
                out["dim"] = list(parse_unit(unit_text).dim)
            except UnitError:
                out["dim"] = ["?", unit_text]
            out.pop("unit", None)
        return out
    if isinstance(obj, list):
        return [_strip_and_quantize(x, pol) for x in obj]
    return obj


# ---------------------------------------------------------------------------
# Node and value hashes
# ---------------------------------------------------------------------------


def node_identity_obj(node: G.Node, pol: TolerancePolicy) -> Any:
    return _strip_and_quantize(node.to_obj(), pol)


def node_hash(node: G.Node, pol: TolerancePolicy) -> str:
    return sha_obj(node_identity_obj(node, pol))


def quantity_value_hash(q: G.Quantity, pol: TolerancePolicy) -> str:
    """Identity of a consumed static value: quantized SI value + dim + uncertainty."""
    return sha_obj(_strip_and_quantize(q.to_obj(), pol))


def output_value_hash(value: Any, unit: str, unc: dict | None, pol: TolerancePolicy) -> str:
    obj: dict = {"value": value, "unit": unit}
    if unc:
        obj["unc"] = unc
    return sha_obj(_strip_and_quantize(obj, pol))


def core_content_hash(project_root: Path, core: G.Core) -> str:
    if not core.path:
        return "sha256:no-core"
    p = project_root / core.path
    try:
        return sha(p.read_bytes())
    except OSError:
        return f"missing:{core.path}"


def graph_hash(doc: G.GraphDoc, pol: TolerancePolicy) -> str:
    """Whole-graph identity: hash of all node identity hashes + connections.
    Stamped onto compiled projections (spec §9.1)."""
    obj = {
        "nodes": {name: node_hash(n, pol) for name, n in sorted(doc.nodes.items())},
        "connections": sorted((c.from_ref, c.to_ref) for c in doc.connections),
        "tools": tool_pins(),
    }
    return sha_obj(obj)
