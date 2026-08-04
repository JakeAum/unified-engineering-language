"""The calibration loop (spec §8): how reality writes back.

Measurements land as **overlay entries** — append-only history per target in
`calibration/overlay.json` (as-designed baseline) or `calibration/<serial>.json`
(as-built per serial number, spec §8 last paragraph). At resolution time the
latest applicable entry replaces the declared value with measured provenance;
because staleness is value-hash-driven, *every consumer of a measured quantity is
flagged stale mechanically* — no bookkeeping, just the hash machinery doing its
job.

Three verdicts per measurement:

- **tightening** (UEL0803, info): inside the current band with a narrower
  uncertainty — the next agent inherits a tighter world; confidence has history.
- **consistent**: inside the band, no tighter; recorded, nothing to say.
- **discrepancy** (UEL0801, warning): outside the predicted/declared band — a
  first-class event: recorded on the overlay entry, and an investigation stub is
  generated (`*.uel.suggested`, not auto-loaded) whose intent is the spec's
  "why was prediction wrong".

Measurements may also target analysis **outputs** (`X.outputs.y`): the measured
value is compared against the lock's computed prediction and recorded as
validation state on the lock entry; the model's hash does not move (the model
didn't change — reality disagreed), so the discrepancy lives as loud validation
state rather than fake staleness.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from . import graph as G
from .conservation import q_interval_si
from .diagnostics import Bag, Span
from .lockfile import Lock
from .resolver import Resolution
from .units import UnitError, parse_unit

OVERLAY_DIR = "calibration"
BASE_OVERLAY = "overlay.json"


# ---------------------------------------------------------------------------
# Overlay files
# ---------------------------------------------------------------------------


def overlay_path(root: Path, serial: str = "") -> Path:
    return root / OVERLAY_DIR / (f"{serial}.json" if serial else BASE_OVERLAY)


def load_overlay(root: Path, serial: str = "") -> dict[str, list[dict]]:
    p = overlay_path(root, serial)
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("targets", {}) if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_overlay(root: Path, targets: dict[str, list[dict]], serial: str = "") -> Path:
    p = overlay_path(root, serial)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"uel_overlay": "0.1", "serial": serial or None, "targets": targets},
                   indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return p


def apply_overlays(res: Resolution, serial: str = "") -> list[str]:
    """Apply latest overlay entries onto resolved quantities (base, then serial).
    Returns the list of applied target refs. Called by the CLI after resolution."""
    applied: list[str] = []
    layers = [load_overlay(res.project.root)]
    if serial:
        layers.append(load_overlay(res.project.root, serial))
    merged: dict[str, dict] = {}
    for layer in layers:
        for target, entries in layer.items():
            if entries:
                latest = max(entries, key=lambda e: e.get("ts", ""))
                merged[target] = latest
    for target, entry in sorted(merged.items()):
        q = _find_quantity(res, target, create=True)
        if q is None:
            continue
        q.value = tuple(entry["value"]) if isinstance(entry["value"], list) else entry["value"]
        q.unit = entry.get("unit", q.unit)
        unc = entry.get("unc")
        q.unc = G.Uncertainty(unc["kind"], unc.get("value")) if unc else G.Uncertainty()
        q.prov = G.Provenance(
            kind="measured",
            site=f"{OVERLAY_DIR}/{serial or 'overlay'}",
            detail=entry.get("source", ""),
            ts=entry.get("ts", ""),
        )
        if entry.get("conf") is not None:
            q.conf = entry["conf"]
        applied.append(target)
    return applied


def _find_quantity(res: Resolution, target: str, create: bool = False) -> Optional[G.Quantity]:
    """Locate the mutable Quantity a target ref names (no diagnostics).

    With `create=True`, a one-segment member on an existing component is
    materialized if absent — as-built measurement legitimately observes
    quantities the design never declared (a shim's mass, a measured runout)."""
    doc = res.doc
    parts = target.split(".")
    for cut in range(len(parts), 0, -1):
        name = ".".join(parts[:cut])
        node = doc.nodes.get(name)
        if node is None:
            continue
        rest = parts[cut:]
        if isinstance(node, (G.Requirement, G.MaterialDef)) and len(rest) == 1:
            return node.quantities.get(rest[0])
        if isinstance(node, G.Component):
            if len(rest) == 1:
                q = node.quantities.get(rest[0])
                if q is None and create:
                    q = G.Quantity()
                    node.quantities[rest[0]] = q
                return q
            if len(rest) == 2 and rest[0] in node.ports:
                return node.ports[rest[0]].attrs.get(rest[1])
        return None
    return None


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def _band_si(q: G.Quantity) -> Optional[tuple[float, float]]:
    return q_interval_si(q)


def _measured_si(m: dict) -> Optional[tuple[float, float, float]]:
    """(si_value, band_lo, band_hi) of the measurement itself."""
    try:
        u = parse_unit(str(m.get("unit", "")))
    except UnitError:
        return None
    v = m.get("value")
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    si = u.to_si(float(v))
    lo = hi = si
    unc = m.get("unc") or {}
    if unc.get("kind") == "abs" and isinstance(unc.get("value"), (int, float)):
        d = abs(unc["value"]) * u.factor
        lo, hi = si - d, si + d
    elif unc.get("kind") == "rel" and isinstance(unc.get("value"), (int, float)):
        d = abs(si) * abs(unc["value"])
        lo, hi = si - d, si + d
    return si, lo, hi


def ingest(res: Resolution, bag: Bag, payload: dict, write_stubs: bool = True) -> dict:
    """Process a measurements file; write overlays and validation state.

    Returns a summary dict {applied, tightened, discrepancies, validated}.
    """
    root = res.project.root
    serial = str(payload.get("serial") or "")
    source = str(payload.get("source", "unattributed measurement"))
    ts = str(payload.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    measurements = payload.get("measurements", [])
    summary = {"applied": 0, "tightened": 0, "discrepancies": 0, "validated": 0}

    targets = load_overlay(root, serial)
    lock = Lock.load(res.project.lock_path)
    lock_dirty = False

    for i, m in enumerate(measurements):
        target = str(m.get("target", ""))
        where = Span(f"measurements[{i}]")
        msi = _measured_si(m)
        if msi is None:
            bag.error("UEL0802", f"measurement {i}: missing/invalid value or unit for '{target}'", where)
            continue
        si, mlo, mhi = msi

        # -- analysis output target: validation, not overlay --
        if ".outputs." in target:
            node_name, out_name = target.split(".outputs.", 1)
            an = res.doc.nodes.get(node_name)
            entry = lock.nodes.get(node_name)
            if not isinstance(an, G.Analysis) or out_name not in an.outputs:
                bag.error("UEL0802", f"measurement target '{target}' is not a declared analysis output", where)
                continue
            pred = entry.outputs.get(out_name) if entry else None
            if pred is None or pred.value is None:
                bag.warning("UEL0802",
                            f"'{target}': no computed prediction to validate against (build first)", where)
                continue
            pq = G.Quantity(
                tuple(pred.value) if isinstance(pred.value, list) else float(pred.value),
                pred.unit,
                G.Uncertainty(pred.unc["kind"], pred.unc.get("value")) if pred.unc else G.Uncertainty(),
            )
            band = _band_si(pq)
            verdict = "consistent"
            if band and (mhi < band[0] or mlo > band[1]):
                verdict = "outside_envelope"
                summary["discrepancies"] += 1
                bag.warning(
                    "UEL0801",
                    f"'{target}': measured {m.get('value')} {m.get('unit')} lies outside the predicted band "
                    f"{_fmt_band(band, pred.unit)} — model confidence flipped; investigation opened",
                    where,
                    reason="a measurement outside a model's predicted envelope is a first-class event (spec §8.4)",
                )
                if write_stubs:
                    _write_investigation_stub(root, target, m, pred, source, ts)
            else:
                summary["validated"] += 1
            if entry is not None:
                entry.run.setdefault("validation", {})[out_name] = {
                    "measured": m.get("value"), "unit": m.get("unit"),
                    "verdict": verdict, "source": source, "ts": ts,
                }
                lock_dirty = True
            continue

        # -- quantity target: overlay entry --
        q = _find_quantity(res, target)
        is_new = False
        if q is None:
            # a 1-segment member on an existing component is a legitimate new
            # as-built observation; anything else is a bad target
            parts = target.rsplit(".", 1)
            owner = res.doc.nodes.get(parts[0]) if len(parts) == 2 else None
            if isinstance(owner, G.Component):
                # compare against geometry-produced value if one exists
                geo_q = None
                if owner.geometry:
                    ge = lock.nodes.get(owner.geometry)
                    go = ge.outputs.get(parts[1]) if ge else None
                    if go is not None and isinstance(go.value, (int, float)):
                        unc = G.Uncertainty()
                        if isinstance(go.unc, dict) and go.unc.get("kind") in ("abs", "rel"):
                            unc = G.Uncertainty(go.unc["kind"], go.unc.get("value"))
                        geo_q = G.Quantity(float(go.value), go.unit, unc)
                q = geo_q or G.Quantity()
                is_new = True
            else:
                bag.error("UEL0802", f"measurement target '{target}' does not name a quantity", where,
                          reason="targets are component/requirement quantities, port attributes, or analysis outputs via '.outputs.'")
                continue
        try:
            mdim = parse_unit(str(m.get("unit", ""))).dim
            qdim = parse_unit(q.unit).dim if q.unit else None
        except UnitError:
            mdim = qdim = None
        if qdim is not None and mdim is not None and mdim != qdim:
            bag.error("UEL0802", f"'{target}': measured in '{m.get('unit')}' but declared in '{q.unit}' "
                      f"(different dimensions)", where)
            continue

        prior_band = _band_si(q)
        entry = {
            "value": m.get("value"), "unit": m.get("unit"),
            **({"unc": m["unc"]} if m.get("unc") else {}),
            "source": source, "ts": ts,
        }
        verdict = "consistent"
        if prior_band is not None and (mhi < prior_band[0] or mlo > prior_band[1]):
            verdict = "discrepancy"
            entry["discrepancy"] = True
            entry["prior"] = q.to_obj()
            summary["discrepancies"] += 1
            bag.warning(
                "UEL0801",
                f"'{target}': measured {m.get('value')} {m.get('unit')} lies outside the declared band "
                f"{_fmt_band(prior_band, q.unit)} — as-built departs from as-designed",
                where,
                reason="the measurement is recorded and now wins (test data always wins an argument with a model, spec §1.4); every consumer flips stale through the hash machinery",
            )
            if write_stubs:
                _write_investigation_stub(root, target, m, None, source, ts)
        elif prior_band is not None and (mhi - mlo) < (prior_band[1] - prior_band[0]) * 0.999:
            verdict = "tightening"
            summary["tightened"] += 1
            bag.info(
                "UEL0803",
                f"'{target}': band tightened from {_fmt_band(prior_band, q.unit)} to "
                f"{_fmt_band((mlo, mhi), q.unit)} by {source}",
                where,
                reason="envelope tightening: the next agent inherits a tighter world (spec §8.3)",
            )
        entry["verdict"] = verdict
        targets.setdefault(target, []).append(entry)
        summary["applied"] += 1

    save_overlay(root, targets, serial)
    if lock_dirty:
        lock.save(res.project.lock_path)
    return summary


def _fmt_band(band: tuple[float, float], unit: str) -> str:
    try:
        u = parse_unit(unit)
        return f"[{u.from_si(band[0]):g}, {u.from_si(band[1]):g}] {unit}".strip()
    except UnitError:
        return f"[{band[0]:g}, {band[1]:g}]"


def _write_investigation_stub(root: Path, target: str, m: dict,
                              pred, source: str, ts: str) -> None:
    safe = target.replace(".", "_").replace("/", "_")
    day = ts[:10].replace("-", "")
    p = root / "analysis" / "investigations" / f"{safe}_{day}.uel.suggested"
    p.parent.mkdir(parents=True, exist_ok=True)
    predicted = ""
    if pred is not None and pred.value is not None:
        predicted = f"  # predicted: {pred.value} {pred.unit}\n"
    p.write_text(
        f"# Investigation stub generated by `uel calibrate` — review, complete, and\n"
        f"# rename to .uel to enter the graph. A discrepancy's resolution is itself\n"
        f"# an analysis (spec §8.4).\n"
        f"analysis Investigate_{safe}_{day} {{\n"
        f"  doc \"Why did {target} measure {m.get('value')} {m.get('unit')} ({source})?\"\n"
        f"{predicted}"
        f"  framing {{\n"
        f"    model investigation.discrepancy\n"
        f"  }}\n"
        f"  core python \"analysis/investigations/{safe}_{day}.py\"\n"
        f"  outputs {{ resolution : dimensionless }}\n"
        f"  judgment pending\n"
        f"}}\n",
        encoding="utf-8",
    )
