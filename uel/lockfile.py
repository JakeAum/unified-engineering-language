"""uel.lock — recorded state of the executable graph (spec §4.5): committed,
sorted, diff-friendly. Recipe hashes with per-part breakdowns, outputs with
quantized hashes (early cutoff), feature claims, assertions, run provenance.
Only entries the scheduler actually ran move, so diffs stay reviewable."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .diagnostics import Bag, Span

LOCK_VERSION = "0.1"

@dataclass
class LockOutput:
    value: Any = None  # float | [lo, hi] | str (artifact path)
    unit: str = ""
    unc: Optional[dict] = None
    hash: str = ""
    artifact: bool = False

    def to_obj(self) -> dict:
        o: dict = {"hash": self.hash}
        if self.value is not None:
            o["value"] = self.value
        if self.unit:
            o["unit"] = self.unit
        if self.unc:
            o["unc"] = self.unc
        if self.artifact:
            o["artifact"] = True
        return o

    @classmethod
    def from_obj(cls, d: dict) -> "LockOutput":
        return cls(d.get("value"), d.get("unit", ""), d.get("unc"), d.get("hash", ""),
                   d.get("artifact", False))

@dataclass
class LockEntry:
    recipe: str = ""
    parts: dict = field(default_factory=dict)  # {"def": h, "core": h, "inputs": {local: h}}
    status: str = "missing"  # fresh | stale | failed | missing
    outputs: dict[str, LockOutput] = field(default_factory=dict)
    features: dict[str, dict] = field(default_factory=dict)  # geometry feature claims
    assertions: list[dict] = field(default_factory=list)
    run: dict = field(default_factory=dict)  # ts, wall_s, tools, seed, engine, verify, validation

    def to_obj(self) -> dict:
        o: dict = {"recipe": self.recipe, "status": self.status}
        if self.parts:
            o["parts"] = self.parts
        if self.outputs:
            o["outputs"] = {k: v.to_obj() for k, v in sorted(self.outputs.items())}
        if self.features:
            o["features"] = dict(sorted(self.features.items()))
        if self.assertions:
            o["assertions"] = self.assertions
        if self.run:
            o["run"] = self.run
        return o

    @classmethod
    def from_obj(cls, d: dict) -> "LockEntry":
        return cls(d.get("recipe", ""), d.get("parts", {}), d.get("status", "missing"),
                   {k: LockOutput.from_obj(v) for k, v in d.get("outputs", {}).items()},
                   d.get("features", {}), d.get("assertions", []), d.get("run", {}))

@dataclass
class Lock:
    edition: str = ""
    tools: dict = field(default_factory=dict)
    nodes: dict[str, LockEntry] = field(default_factory=dict)

    def to_obj(self) -> dict:
        return {"uel_lock": LOCK_VERSION, "edition": self.edition, "tools": self.tools,
                "nodes": {k: v.to_obj() for k, v in sorted(self.nodes.items())}}

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_obj(), indent=2, sort_keys=True,
                                   ensure_ascii=False) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path, bag: Bag | None = None) -> "Lock":
        if not path.is_file(): return cls()
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            if bag is not None:
                bag.error("UEL0003", f"cannot read {path.name}: {e}", Span(path.name),
                          reason="delete or restore the lock; `uel build` regenerates it")
            return cls()
        if not isinstance(d, dict) or d.get("uel_lock") != LOCK_VERSION:
            if bag is not None:
                bag.warning("UEL0003", f"{path.name} has unknown version; ignoring it", Span(path.name))
            return cls()
        return cls(d.get("edition", ""), d.get("tools", {}),
                   {k: LockEntry.from_obj(v) for k, v in d.get("nodes", {}).items()})
