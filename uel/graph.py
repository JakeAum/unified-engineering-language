"""The semantic graph — UEL's data model, defined before and independently of syntax.

Kernel kinds (spec §2): component, port (owned by a component), quantity, and
analysis (the claim/argument node, spec §3). Library kinds the kernel must be able
to represent but ships as versioned libraries (spec §5.3): domain, claim (structural-
assumption taxonomy), material, process (DFM ruleset). Requirements are kernel-adjacent:
they are the anchors intents point at.

Serialization: every node maps to a plain JSON object via `to_obj`/`from_obj`, with
omit-empty semantics, encoded by `uel.canon`. Two field classes exist and are marked
below:

- identity fields — part of a node's semantic content; participate in hashing.
- record fields — provenance-of-authorship metadata (`src` sites, timestamps, doc,
  judgment prose). Kept in the graph, excluded from recipe hashes so that moving a
  declaration to another line, or writing down judgment, never invalidates physics.
  (Hashing itself lands in `uel.hashing`; the identity/record split is declared here.)

This module is deliberately dependency-free and syntax-free: the parser produces it,
the checker consumes it, and conformance grades its round-trip stability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

from .canon import canonical_bytes, canonical_str
from . import EDITION, SCHEMA_VERSION

# ---------------------------------------------------------------------------
# Errors collected during reading
# ---------------------------------------------------------------------------


@dataclass
class SchemaError:
    path: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - convenience
        return f"{self.path}: {self.message}"


class _Reader:
    """Field extraction with error accumulation instead of exceptions."""

    def __init__(self) -> None:
        self.errors: list[SchemaError] = []

    def err(self, path: str, message: str) -> None:
        self.errors.append(SchemaError(path, message))

    def obj(self, v: Any, path: str) -> dict:
        if not isinstance(v, dict):
            self.err(path, f"expected object, got {type(v).__name__}")
            return {}
        return v

    def str_(self, d: dict, key: str, path: str, default: str = "", required: bool = False) -> str:
        v = d.get(key, None)
        if v is None:
            if required:
                self.err(path, f"missing required field '{key}'")
            return default
        if not isinstance(v, str):
            self.err(f"{path}.{key}", f"expected string, got {type(v).__name__}")
            return default
        return v

    def num(self, d: dict, key: str, path: str) -> Optional[float]:
        v = d.get(key, None)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self.err(f"{path}.{key}", f"expected number, got {type(v).__name__}")
            return None
        return float(v)

    def int_(self, d: dict, key: str, path: str) -> Optional[int]:
        v = d.get(key, None)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, int):
            self.err(f"{path}.{key}", f"expected integer, got {type(v).__name__}")
            return None
        return v

    def bool_(self, d: dict, key: str, path: str, default: bool = False) -> bool:
        v = d.get(key, None)
        if v is None:
            return default
        if not isinstance(v, bool):
            self.err(f"{path}.{key}", f"expected boolean, got {type(v).__name__}")
            return default
        return v

    def enum(self, d: dict, key: str, path: str, allowed: tuple, default: str) -> str:
        v = self.str_(d, key, path, default=default)
        if v not in allowed:
            self.err(f"{path}.{key}", f"expected one of {allowed}, got {v!r}")
            return default
        return v

    def unknown_fields(self, d: dict, known: tuple, path: str) -> None:
        for k in d:
            if k not in known:
                self.err(f"{path}.{k}", "unknown field")


def _put(d: dict, key: str, value: Any) -> None:
    """Omit-empty insertion: None, "", {}, [] are omitted from canonical form."""
    if value is None or value == "" or value == {} or value == []:
        return
    d[key] = value


# ---------------------------------------------------------------------------
# Quantity — (value or interval, unit, uncertainty, provenance, confidence)
# ---------------------------------------------------------------------------

Scalar = float
Interval = tuple[float, float]
Value = Union[None, Scalar, Interval]  # None = declared-but-TBD


@dataclass
class Uncertainty:
    """kind: 'none' | 'abs' (± value in the quantity's unit) | 'rel' (± fraction)
    | 'cal' (calibration-pending: unknown-but-declared, treated as wide)."""

    kind: str = "none"  # identity
    value: Optional[float] = None  # identity

    def to_obj(self) -> Optional[dict]:
        if self.kind == "none":
            return None
        o: dict = {"kind": self.kind}
        _put(o, "value", self.value)
        return o

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Uncertainty":
        if v is None:
            return cls()
        d = r.obj(v, path)
        kind = r.enum(d, "kind", path, ("none", "abs", "rel", "cal"), "none")
        value = r.num(d, "value", path)
        if kind in ("abs", "rel") and value is None:
            r.err(path, f"uncertainty kind '{kind}' requires a value")
        r.unknown_fields(d, ("kind", "value"), path)
        return cls(kind, value)


@dataclass
class Provenance:
    """Where a value came from. `kind` is identity (a measured value that replaces a
    declared one is a semantic change even at equal value is NOT true — the value
    drives staleness; kind rides along for queries). site/detail/ts are record fields.
    kind: declared | measured | vendor | derived | estimate
    """

    kind: str = "declared"
    site: str = ""  # record: file:line or node ref that authored the value
    detail: str = ""  # record: e.g. "datasheet p.3", "test W12 run 3"
    ts: str = ""  # record: ISO timestamp for volatile observations

    def to_obj(self) -> Optional[dict]:
        o: dict = {}
        if self.kind != "declared":
            o["kind"] = self.kind
        _put(o, "site", self.site)
        _put(o, "detail", self.detail)
        _put(o, "ts", self.ts)
        return o or None

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Provenance":
        if v is None:
            return cls()
        d = r.obj(v, path)
        kind = r.enum(d, "kind", path, ("declared", "measured", "vendor", "derived", "estimate"), "declared")
        site = r.str_(d, "site", path)
        detail = r.str_(d, "detail", path)
        ts = r.str_(d, "ts", path)
        r.unknown_fields(d, ("kind", "site", "detail", "ts"), path)
        return cls(kind, site, detail, ts)


@dataclass
class Quantity:
    """Every scalar in the graph. Point values are the degenerate case of intervals."""

    value: Value = None  # identity: float, (lo, hi), or None (TBD)
    unit: str = ""  # identity: surface unit expression ("" = dimensionless)
    unc: Uncertainty = field(default_factory=Uncertainty)  # identity
    prov: Provenance = field(default_factory=Provenance)  # kind: identity-lite; rest record
    conf: Optional[float] = None  # record: confidence 0..1

    def is_interval(self) -> bool:
        return isinstance(self.value, tuple)

    def to_obj(self) -> dict:
        o: dict = {}
        if self.value is not None:
            if isinstance(self.value, tuple):
                o["value"] = [self.value[0], self.value[1]]
            else:
                o["value"] = self.value
        _put(o, "unit", self.unit)
        _put(o, "unc", self.unc.to_obj())
        _put(o, "prov", self.prov.to_obj())
        _put(o, "conf", self.conf)
        return o

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Quantity":
        d = r.obj(v, path)
        raw = d.get("value", None)
        value: Value = None
        if raw is not None:
            if isinstance(raw, list):
                if len(raw) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in raw):
                    r.err(f"{path}.value", "interval must be [lo, hi] numbers")
                else:
                    lo, hi = float(raw[0]), float(raw[1])
                    if lo > hi:
                        r.err(f"{path}.value", f"interval lo {lo} > hi {hi}")
                    value = (lo, hi)
            elif isinstance(raw, bool) or not isinstance(raw, (int, float)):
                r.err(f"{path}.value", f"expected number or [lo, hi], got {type(raw).__name__}")
            else:
                value = float(raw)
        unit = r.str_(d, "unit", path)
        unc = Uncertainty.from_obj(d.get("unc"), r, f"{path}.unc")
        prov = Provenance.from_obj(d.get("prov"), r, f"{path}.prov")
        conf = r.num(d, "conf", path)
        if conf is not None and not (0.0 <= conf <= 1.0):
            r.err(f"{path}.conf", f"confidence must be in [0, 1], got {conf}")
        r.unknown_fields(d, ("value", "unit", "unc", "prov", "conf"), path)
        return cls(value, unit, unc, prov, conf)


def _quantities_from(d: dict, key: str, r: _Reader, path: str) -> dict[str, Quantity]:
    out: dict[str, Quantity] = {}
    raw = d.get(key)
    if raw is None:
        return out
    for name, qv in r.obj(raw, f"{path}.{key}").items():
        out[name] = Quantity.from_obj(qv, r, f"{path}.{key}.{name}")
    return out


def _quantities_obj(qs: dict[str, Quantity]) -> dict:
    return {k: v.to_obj() for k, v in qs.items()}


# ---------------------------------------------------------------------------
# Envelope — the fence of assumptions inside which a thing is valid (spec §2.5)
# ---------------------------------------------------------------------------


@dataclass
class Predicate:
    """Value predicate over one variable: var in [lo, hi] (either bound optional)."""

    lo: Optional[float] = None  # identity
    hi: Optional[float] = None  # identity
    unit: str = ""  # identity

    def to_obj(self) -> dict:
        o: dict = {}
        _put(o, "lo", self.lo)
        _put(o, "hi", self.hi)
        _put(o, "unit", self.unit)
        return o

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Predicate":
        d = r.obj(v, path)
        lo = r.num(d, "lo", path)
        hi = r.num(d, "hi", path)
        unit = r.str_(d, "unit", path)
        if lo is None and hi is None:
            r.err(path, "predicate needs at least one bound (lo or hi)")
        if lo is not None and hi is not None and lo > hi:
            r.err(path, f"predicate lo {lo} > hi {hi}")
        r.unknown_fields(d, ("lo", "hi", "unit"), path)
        return cls(lo, hi, unit)


@dataclass
class Envelope:
    """predicates: var -> Predicate (SMT-decidable layer, boxes in v0.1).
    claims: structural claims made (claim -> rationale), e.g. assume rigid.
    requires: structural claims required of upstream (claim -> rationale)."""

    predicates: dict[str, Predicate] = field(default_factory=dict)  # identity
    claims: dict[str, str] = field(default_factory=dict)  # identity (rationale: record-lite, kept)
    requires: dict[str, str] = field(default_factory=dict)  # identity

    def is_empty(self) -> bool:
        return not (self.predicates or self.claims or self.requires)

    def to_obj(self) -> Optional[dict]:
        o: dict = {}
        _put(o, "predicates", {k: v.to_obj() for k, v in self.predicates.items()})
        _put(o, "claims", dict(self.claims))
        _put(o, "requires", dict(self.requires))
        return o or None

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Envelope":
        if v is None:
            return cls()
        d = r.obj(v, path)
        preds = {
            var: Predicate.from_obj(pv, r, f"{path}.predicates.{var}")
            for var, pv in r.obj(d.get("predicates", {}), f"{path}.predicates").items()
        }
        claims = _str_map(d.get("claims"), r, f"{path}.claims")
        requires = _str_map(d.get("requires"), r, f"{path}.requires")
        r.unknown_fields(d, ("predicates", "claims", "requires"), path)
        return cls(preds, claims, requires)


def _str_map(v: Any, r: _Reader, path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if v is None:
        return out
    for k, s in r.obj(v, path).items():
        if not isinstance(s, str):
            r.err(f"{path}.{k}", f"expected string rationale, got {type(s).__name__}")
            continue
        out[k] = s
    return out


def _str_list(v: Any, r: _Reader, path: str) -> list[str]:
    out: list[str] = []
    if v is None:
        return out
    if not isinstance(v, list):
        r.err(path, f"expected list of strings, got {type(v).__name__}")
        return out
    for i, s in enumerate(v):
        if not isinstance(s, str):
            r.err(f"{path}[{i}]", f"expected string, got {type(s).__name__}")
        else:
            out.append(s)
    return sorted(set(out))


# ---------------------------------------------------------------------------
# Ports (spec §2.2)
# ---------------------------------------------------------------------------


@dataclass
class Port:
    domain: str = ""  # identity: e.g. "electrical", "mechanical.translation"
    dir: str = "inout"  # identity: in | out | inout (w.r.t. the owning component)
    attrs: dict[str, Quantity] = field(default_factory=dict)  # identity
    protocol: str = ""  # identity: data ports only
    doc: str = ""  # record

    def to_obj(self) -> dict:
        o: dict = {"domain": self.domain}
        if self.dir != "inout":
            o["dir"] = self.dir
        _put(o, "attrs", _quantities_obj(self.attrs))
        _put(o, "protocol", self.protocol)
        _put(o, "doc", self.doc)
        return o

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Port":
        d = r.obj(v, path)
        domain = r.str_(d, "domain", path, required=True)
        dir_ = r.enum(d, "dir", path, ("in", "out", "inout"), "inout")
        attrs = _quantities_from(d, "attrs", r, path)
        protocol = r.str_(d, "protocol", path)
        doc = r.str_(d, "doc", path)
        r.unknown_fields(d, ("domain", "dir", "attrs", "protocol", "doc"), path)
        return cls(domain, dir_, attrs, protocol, doc)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


@dataclass
class Budget:
    op: str = "<="  # identity
    limit: Quantity = field(default_factory=Quantity)  # identity
    at_qty: Optional[int] = None  # identity: cost @ qty N

    def to_obj(self) -> dict:
        o: dict = {"op": self.op, "limit": self.limit.to_obj()}
        _put(o, "at_qty", self.at_qty)
        return o

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Budget":
        d = r.obj(v, path)
        op = r.enum(d, "op", path, ("<=", ">="), "<=")
        limit = Quantity.from_obj(d.get("limit", {}), r, f"{path}.limit")
        at_qty = r.int_(d, "at_qty", path)
        r.unknown_fields(d, ("op", "limit", "at_qty"), path)
        return cls(op, limit, at_qty)


@dataclass
class Contain:
    ref: str = ""  # identity
    count: int = 1  # identity

    def to_obj(self) -> dict:
        o: dict = {"ref": self.ref}
        if self.count != 1:
            o["count"] = self.count
        return o

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Contain":
        d = r.obj(v, path)
        ref = r.str_(d, "ref", path, required=True)
        count = r.int_(d, "count", path)
        if count is not None and count < 1:
            r.err(f"{path}.count", f"count must be >= 1, got {count}")
            count = 1
        r.unknown_fields(d, ("ref", "count"), path)
        return cls(ref, count if count is not None else 1)


@dataclass
class Datasheet:
    """An imported static reference for a component (spec §7.2): hashed once per
    revision; extracted values live as vendor-provenance quantities on the node."""

    source: str = ""  # identity: path or URI of the datasheet artifact
    sha256: str = ""  # identity: hash of the artifact revision
    title: str = ""  # record

    def to_obj(self) -> Optional[dict]:
        o: dict = {}
        _put(o, "source", self.source)
        _put(o, "sha256", self.sha256)
        _put(o, "title", self.title)
        return o or None

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> Optional["Datasheet"]:
        if v is None:
            return None
        d = r.obj(v, path)
        source = r.str_(d, "source", path, required=True)
        sha256 = r.str_(d, "sha256", path)
        title = r.str_(d, "title", path)
        r.unknown_fields(d, ("source", "sha256", "title"), path)
        return cls(source, sha256, title)


@dataclass
class Component:
    """A thing that occupies a region of spacetime and exchanges conserved
    quantities with its neighbors — at a declared abstraction level (spec §2.3)."""

    name: str = ""
    level: str = "functional"  # identity: functional | behavioral | physical
    ports: dict[str, Port] = field(default_factory=dict)  # identity
    quantities: dict[str, Quantity] = field(default_factory=dict)  # identity
    budgets: dict[str, Budget] = field(default_factory=dict)  # identity
    envelope: Envelope = field(default_factory=Envelope)  # identity
    contains: list[Contain] = field(default_factory=list)  # identity
    realizes: str = ""  # identity: the binding edge (physical -> functional)
    process: str = ""  # identity: manufacturing process ref (activates DFM ruleset)
    material: str = ""  # identity: material ref
    geometry: str = ""  # identity: ref to the geometry analysis node producing this shape
    datasheet: Optional[Datasheet] = None  # identity
    doc: str = ""  # record
    src: str = ""  # record: file:line of declaration

    KIND = "component"

    def to_obj(self) -> dict:
        o: dict = {"kind": self.KIND, "level": self.level}
        _put(o, "ports", {k: v.to_obj() for k, v in self.ports.items()})
        _put(o, "quantities", _quantities_obj(self.quantities))
        _put(o, "budgets", {k: v.to_obj() for k, v in self.budgets.items()})
        _put(o, "envelope", self.envelope.to_obj())
        _put(o, "contains", [c.to_obj() for c in sorted(self.contains, key=lambda c: c.ref)])
        _put(o, "realizes", self.realizes)
        _put(o, "process", self.process)
        _put(o, "material", self.material)
        _put(o, "geometry", self.geometry)
        _put(o, "datasheet", self.datasheet.to_obj() if self.datasheet else None)
        _put(o, "doc", self.doc)
        _put(o, "src", self.src)
        return o

    @classmethod
    def from_obj(cls, name: str, d: dict, r: _Reader, path: str) -> "Component":
        level = r.enum(d, "level", path, ("functional", "behavioral", "physical"), "functional")
        ports = {
            pn: Port.from_obj(pv, r, f"{path}.ports.{pn}")
            for pn, pv in r.obj(d.get("ports", {}), f"{path}.ports").items()
        }
        quantities = _quantities_from(d, "quantities", r, path)
        budgets = {
            bn: Budget.from_obj(bv, r, f"{path}.budgets.{bn}")
            for bn, bv in r.obj(d.get("budgets", {}), f"{path}.budgets").items()
        }
        envelope = Envelope.from_obj(d.get("envelope"), r, f"{path}.envelope")
        contains = sorted(
            (Contain.from_obj(cv, r, f"{path}.contains[{i}]")
             for i, cv in enumerate(d.get("contains", []) or [])),
            key=lambda c: c.ref,
        )
        realizes = r.str_(d, "realizes", path)
        process = r.str_(d, "process", path)
        material = r.str_(d, "material", path)
        geometry = r.str_(d, "geometry", path)
        datasheet = Datasheet.from_obj(d.get("datasheet"), r, f"{path}.datasheet")
        doc = r.str_(d, "doc", path)
        src = r.str_(d, "src", path)
        r.unknown_fields(
            d,
            ("kind", "level", "ports", "quantities", "budgets", "envelope", "contains",
             "realizes", "process", "material", "geometry", "datasheet", "doc", "src"),
            path,
        )
        return cls(name, level, ports, quantities, budgets, envelope, contains,
                   realizes, process, material, geometry, datasheet, doc, src)


@dataclass
class Requirement:
    name: str = ""
    text: str = ""  # identity (the requirement IS its text)
    quantities: dict[str, Quantity] = field(default_factory=dict)  # identity
    doc: str = ""  # record
    src: str = ""  # record

    KIND = "requirement"

    def to_obj(self) -> dict:
        o: dict = {"kind": self.KIND}
        _put(o, "text", self.text)
        _put(o, "quantities", _quantities_obj(self.quantities))
        _put(o, "doc", self.doc)
        _put(o, "src", self.src)
        return o

    @classmethod
    def from_obj(cls, name: str, d: dict, r: _Reader, path: str) -> "Requirement":
        text = r.str_(d, "text", path)
        quantities = _quantities_from(d, "quantities", r, path)
        doc = r.str_(d, "doc", path)
        src = r.str_(d, "src", path)
        r.unknown_fields(d, ("kind", "text", "quantities", "doc", "src"), path)
        return cls(name, text, quantities, doc, src)


@dataclass
class Intent:
    ref: str = ""  # identity: requirement or decision this analysis serves
    text: str = ""  # record: the question, restated

    def to_obj(self) -> Optional[dict]:
        o: dict = {}
        _put(o, "ref", self.ref)
        _put(o, "text", self.text)
        return o or None

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Intent":
        if v is None:
            return cls()
        d = r.obj(v, path)
        ref = r.str_(d, "ref", path)
        text = r.str_(d, "text", path)
        r.unknown_fields(d, ("ref", "text"), path)
        return cls(ref, text)


@dataclass
class Framing:
    """The creative act (spec §3.1): chosen physics model, drawn boundary,
    assumptions with rationale. The envelope carries both layers of the fence."""

    model: str = ""  # identity: e.g. "beam.euler_bernoulli"
    envelope: Envelope = field(default_factory=Envelope)  # identity

    def to_obj(self) -> Optional[dict]:
        o: dict = {}
        _put(o, "model", self.model)
        _put(o, "envelope", self.envelope.to_obj())
        return o or None

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Framing":
        if v is None:
            return cls()
        d = r.obj(v, path)
        model = r.str_(d, "model", path)
        envelope = Envelope.from_obj(d.get("envelope"), r, f"{path}.envelope")
        r.unknown_fields(d, ("model", "envelope"), path)
        return cls(model, envelope)


@dataclass
class Core:
    """The executable recipe (spec §3.2). Python cores are opaque: compile time
    never opens them; the file's *content hash* participates in the recipe hash
    (the path does not, so moving a file without changing it invalidates
    nothing). v0.2 expr/stub cores (ADR-0005) are transparent: the canonical
    formatted body is stored in `text`, type-checked at compile time, and IS the
    content that hashes."""

    lang: str = "python"  # identity: python | expr | stub
    path: str = ""  # record-as-locator (content is identity, fetched at hash time)
    text: str = ""  # identity: canonical expr/stub body (empty for python cores)
    # v0.3 (ADR-0008): what wraps the black box is declarable and hashes.
    tools: dict[str, str] = field(default_factory=dict)  # identity: tool name -> pinned version
    interface: Optional[Datasheet] = None  # identity: manifest defining the wrapped module

    def to_obj(self) -> Optional[dict]:
        o: dict = {}
        if self.lang != "python":
            o["lang"] = self.lang
        _put(o, "path", self.path)
        _put(o, "text", self.text)
        _put(o, "tools", dict(sorted(self.tools.items())))
        _put(o, "interface", self.interface.to_obj() if self.interface else None)
        return o or None

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Core":
        if v is None:
            return cls()
        d = r.obj(v, path)
        lang = r.str_(d, "lang", path, default="python")
        p = r.str_(d, "path", path)
        text = r.str_(d, "text", path)
        tools = _str_map(d.get("tools"), r, f"{path}.tools")
        interface = Datasheet.from_obj(d.get("interface"), r, f"{path}.interface")
        r.unknown_fields(d, ("lang", "path", "text", "tools", "interface"), path)
        return cls(lang, p, text, tools, interface)


@dataclass
class OutputDecl:
    unit: str = ""  # identity
    unc: bool = False  # identity: output carries uncertainty
    artifact: bool = False  # identity: file artifact (mesh, field) rather than quantity
    # v0.2 (ADR-0007): the acceptance bound this output must satisfy, checked
    # against the lock after every build — requirement satisfaction is computed,
    # not narrated. Exactly one of target_ref / target_value when target_op set.
    target_op: str = ""  # identity: "" | ">=" | "<="
    target_ref: str = ""  # identity: canonical value reference
    target_value: Optional[Quantity] = None  # identity: literal bound

    def to_obj(self) -> dict:
        o: dict = {}
        _put(o, "unit", self.unit)
        if self.unc:
            o["unc"] = True
        if self.artifact:
            o["artifact"] = True
        if self.target_op:
            t: dict = {"op": self.target_op}
            _put(t, "ref", self.target_ref)
            _put(t, "value", self.target_value.to_obj() if self.target_value else None)
            o["target"] = t
        return o

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "OutputDecl":
        d = r.obj(v, path)
        unit = r.str_(d, "unit", path)
        unc = r.bool_(d, "unc", path)
        artifact = r.bool_(d, "artifact", path)
        target_op, target_ref, target_value = "", "", None
        traw = d.get("target")
        if traw is not None:
            td = r.obj(traw, f"{path}.target")
            target_op = r.enum(td, "op", f"{path}.target", (">=", "<="), ">=")
            target_ref = r.str_(td, "ref", f"{path}.target")
            if "value" in td:
                target_value = Quantity.from_obj(td["value"], r, f"{path}.target.value")
            if bool(target_ref) == (target_value is not None):
                r.err(f"{path}.target", "target carries exactly one of 'ref' or 'value'")
            r.unknown_fields(td, ("op", "ref", "value"), f"{path}.target")
        r.unknown_fields(d, ("unit", "unc", "artifact", "target"), path)
        return cls(unit, unc, artifact, target_op, target_ref, target_value)


@dataclass
class Judgment:
    """The sense-making, recorded explicitly with residual doubts (spec §3.1).
    Record fields: editing judgment prose never re-runs physics."""

    status: str = "pending"  # pending | accepted | rejected | superseded
    text: str = ""
    doubts: str = ""

    def to_obj(self) -> Optional[dict]:
        o: dict = {}
        if self.status != "pending":
            o["status"] = self.status
        _put(o, "text", self.text)
        _put(o, "doubts", self.doubts)
        return o or None

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Judgment":
        if v is None:
            return cls()
        d = r.obj(v, path)
        status = r.enum(d, "status", path, ("pending", "accepted", "rejected", "superseded"), "pending")
        text = r.str_(d, "text", path)
        doubts = r.str_(d, "doubts", path)
        r.unknown_fields(d, ("status", "text", "doubts"), path)
        return cls(status, text, doubts)


@dataclass
class Verify:
    """A verification contract (v0.3, ADR-0008): a machine-checkable reason to
    believe this analysis, graded by the kernel instead of asserted by the author.

    kind 'against' — cross-check an output vs another node's value (lock-vs-lock,
    judged at check time). kind 'monotone' — perturb an input at build time and
    require the output to move the declared direction. kind 'case' — re-run the
    core on a golden input file and require the expected outputs, within tol.
    `tol_unit` empty means relative (tol is a fraction); else absolute in that
    unit (the natural spelling for levels: `within 0.5 dB`)."""

    kind: str = "against"  # identity: against | monotone | case
    output: str = ""  # identity
    ref: str = ""  # identity (against)
    known: str = ""  # identity (monotone)
    direction: str = ""  # identity (monotone): rising | falling
    path: str = ""  # identity (case)
    tol: Optional[float] = None  # identity
    tol_unit: str = ""  # identity

    def to_obj(self) -> dict:
        o: dict = {"kind": self.kind}
        _put(o, "output", self.output)
        _put(o, "ref", self.ref)
        _put(o, "known", self.known)
        _put(o, "direction", self.direction)
        _put(o, "path", self.path)
        _put(o, "tol", self.tol)
        _put(o, "tol_unit", self.tol_unit)
        return o

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Verify":
        d = r.obj(v, path)
        kind = r.enum(d, "kind", path, ("against", "monotone", "case"), "against")
        output = r.str_(d, "output", path)
        ref = r.str_(d, "ref", path)
        known = r.str_(d, "known", path)
        direction = r.str_(d, "direction", path)
        if direction and direction not in ("rising", "falling"):
            r.err(f"{path}.direction", f"expected rising|falling, got {direction!r}")
            direction = ""
        p = r.str_(d, "path", path)
        tol = r.num(d, "tol", path)
        tol_unit = r.str_(d, "tol_unit", path)
        r.unknown_fields(d, ("kind", "output", "ref", "known", "direction", "path", "tol", "tol_unit"), path)
        return cls(kind, output, ref, known, direction, p, tol, tol_unit)

    def sort_key(self) -> tuple:
        return (self.kind, self.output, self.ref, self.known, self.path)


@dataclass
class Analysis:
    """Engineering's unit of work: an argument that a claim about the system is
    justified (spec §3). akind 'geometry' marks shape-producing nodes (spec §6.2),
    which additionally must assert their topology; the shell is identical."""

    name: str = ""
    akind: str = "analysis"  # identity: analysis | geometry
    intent: Intent = field(default_factory=Intent)  # identity (ref); text is record
    framing: Framing = field(default_factory=Framing)  # identity
    knowns: dict[str, str] = field(default_factory=dict)  # identity: local name -> graph ref
    params: dict[str, Quantity] = field(default_factory=dict)  # identity: literal inputs
    core: Core = field(default_factory=Core)  # identity via content
    outputs: dict[str, OutputDecl] = field(default_factory=dict)  # identity
    verifies: list[Verify] = field(default_factory=list)  # identity (v0.3)
    judgment: Judgment = field(default_factory=Judgment)  # record
    doc: str = ""  # record
    src: str = ""  # record

    KIND = "analysis"

    def to_obj(self) -> dict:
        o: dict = {"kind": self.KIND}
        if self.akind != "analysis":
            o["akind"] = self.akind
        _put(o, "intent", self.intent.to_obj())
        _put(o, "framing", self.framing.to_obj())
        _put(o, "knowns", dict(self.knowns))
        _put(o, "params", _quantities_obj(self.params))
        _put(o, "core", self.core.to_obj())
        _put(o, "outputs", {k: v.to_obj() for k, v in self.outputs.items()})
        _put(o, "verifies", [v.to_obj() for v in sorted(self.verifies, key=Verify.sort_key)])
        _put(o, "judgment", self.judgment.to_obj())
        _put(o, "doc", self.doc)
        _put(o, "src", self.src)
        return o

    @classmethod
    def from_obj(cls, name: str, d: dict, r: _Reader, path: str) -> "Analysis":
        akind = r.enum(d, "akind", path, ("analysis", "geometry"), "analysis")
        intent = Intent.from_obj(d.get("intent"), r, f"{path}.intent")
        framing = Framing.from_obj(d.get("framing"), r, f"{path}.framing")
        knowns = _str_map(d.get("knowns"), r, f"{path}.knowns")
        params = _quantities_from(d, "params", r, path)
        core = Core.from_obj(d.get("core"), r, f"{path}.core")
        outputs = {
            on: OutputDecl.from_obj(ov, r, f"{path}.outputs.{on}")
            for on, ov in r.obj(d.get("outputs", {}), f"{path}.outputs").items()
        }
        verifies = sorted(
            (Verify.from_obj(vv, r, f"{path}.verifies[{i}]")
             for i, vv in enumerate(d.get("verifies", []) or [])),
            key=Verify.sort_key,
        )
        judgment = Judgment.from_obj(d.get("judgment"), r, f"{path}.judgment")
        doc = r.str_(d, "doc", path)
        src = r.str_(d, "src", path)
        r.unknown_fields(
            d,
            ("kind", "akind", "intent", "framing", "knowns", "params", "core",
             "outputs", "verifies", "judgment", "doc", "src"),
            path,
        )
        return cls(name, akind, intent, framing, knowns, params, core, outputs,
                   verifies, judgment, doc, src)


# --- Library kinds ----------------------------------------------------------


@dataclass
class EffortFlow:
    name: str = ""  # identity: attribute name, e.g. "voltage"
    unit: str = ""  # identity: canonical unit, e.g. "V"

    def to_obj(self) -> Optional[dict]:
        o: dict = {}
        _put(o, "name", self.name)
        _put(o, "unit", self.unit)
        return o or None

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "EffortFlow":
        if v is None:
            return cls()
        d = r.obj(v, path)
        name = r.str_(d, "name", path)
        unit = r.str_(d, "unit", path)
        r.unknown_fields(d, ("name", "unit"), path)
        return cls(name, unit)


@dataclass
class DomainDef:
    """A port domain (spec §2.2 table): an effort/flow pair whose product is power,
    or a material/data domain. Library, not kernel — the kernel checks against
    whatever domains are in scope."""

    name: str = ""
    dclass: str = "power"  # identity: power | material | data
    effort: EffortFlow = field(default_factory=EffortFlow)  # identity
    flow: EffortFlow = field(default_factory=EffortFlow)  # identity
    doc: str = ""  # record
    src: str = ""  # record

    KIND = "domain"

    def to_obj(self) -> dict:
        o: dict = {"kind": self.KIND, "dclass": self.dclass}
        _put(o, "effort", self.effort.to_obj())
        _put(o, "flow", self.flow.to_obj())
        _put(o, "doc", self.doc)
        _put(o, "src", self.src)
        return o

    @classmethod
    def from_obj(cls, name: str, d: dict, r: _Reader, path: str) -> "DomainDef":
        dclass = r.enum(d, "dclass", path, ("power", "material", "data"), "power")
        effort = EffortFlow.from_obj(d.get("effort"), r, f"{path}.effort")
        flow = EffortFlow.from_obj(d.get("flow"), r, f"{path}.flow")
        doc = r.str_(d, "doc", path)
        src = r.str_(d, "src", path)
        if dclass == "power" and (not effort.name or not flow.name):
            r.err(path, "power domain requires both effort and flow definitions")
        r.unknown_fields(d, ("kind", "dclass", "effort", "flow", "doc", "src"), path)
        return cls(name, dclass, effort, flow, doc, src)


@dataclass
class ClaimDef:
    """A structural claim in the assumption taxonomy (spec §2.5): a statement about
    dropped physics, with hand-authored entailment/exclusion rules."""

    name: str = ""
    entails: list[str] = field(default_factory=list)  # identity
    excludes: list[str] = field(default_factory=list)  # identity
    doc: str = ""  # record
    src: str = ""  # record

    KIND = "claim"

    def to_obj(self) -> dict:
        o: dict = {"kind": self.KIND}
        _put(o, "entails", sorted(self.entails))
        _put(o, "excludes", sorted(self.excludes))
        _put(o, "doc", self.doc)
        _put(o, "src", self.src)
        return o

    @classmethod
    def from_obj(cls, name: str, d: dict, r: _Reader, path: str) -> "ClaimDef":
        entails = _str_list(d.get("entails"), r, f"{path}.entails")
        excludes = _str_list(d.get("excludes"), r, f"{path}.excludes")
        doc = r.str_(d, "doc", path)
        src = r.str_(d, "src", path)
        r.unknown_fields(d, ("kind", "entails", "excludes", "doc", "src"), path)
        return cls(name, entails, excludes, doc, src)


@dataclass
class MaterialDef:
    name: str = ""
    quantities: dict[str, Quantity] = field(default_factory=dict)  # identity
    doc: str = ""  # record
    src: str = ""  # record

    KIND = "material"

    def to_obj(self) -> dict:
        o: dict = {"kind": self.KIND}
        _put(o, "quantities", _quantities_obj(self.quantities))
        _put(o, "doc", self.doc)
        _put(o, "src", self.src)
        return o

    @classmethod
    def from_obj(cls, name: str, d: dict, r: _Reader, path: str) -> "MaterialDef":
        quantities = _quantities_from(d, "quantities", r, path)
        doc = r.str_(d, "doc", path)
        src = r.str_(d, "src", path)
        r.unknown_fields(d, ("kind", "quantities", "doc", "src"), path)
        return cls(name, quantities, doc, src)


@dataclass
class DfmRule:
    """One statically checkable claim of shop knowledge (spec §7.1).
    op '>='/'<=': bound `feature` (a geometry-declared feature quantity) by `limit`.
    op 'forbid'/'require': the feature must be absent/zero or present/nonzero."""

    feature: str = ""  # identity
    op: str = ">="  # identity
    limit: Optional[Quantity] = None  # identity
    message: str = ""  # record (the why; shown in diagnostics)

    def to_obj(self) -> dict:
        o: dict = {"feature": self.feature, "op": self.op}
        _put(o, "limit", self.limit.to_obj() if self.limit else None)
        _put(o, "message", self.message)
        return o

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "DfmRule":
        d = r.obj(v, path)
        feature = r.str_(d, "feature", path, required=True)
        op = r.enum(d, "op", path, (">=", "<=", "forbid", "require"), ">=")
        limit = Quantity.from_obj(d["limit"], r, f"{path}.limit") if "limit" in d else None
        if op in (">=", "<=") and limit is None:
            r.err(path, f"rule op '{op}' requires a limit quantity")
        message = r.str_(d, "message", path)
        r.unknown_fields(d, ("feature", "op", "limit", "message"), path)
        return cls(feature, op, limit, message)


@dataclass
class ProcessDef:
    """A manufacturing process: a DFM ruleset activated at binding (spec §2.3, §7.1)."""

    name: str = ""
    rules: dict[str, DfmRule] = field(default_factory=dict)  # identity
    doc: str = ""  # record
    src: str = ""  # record

    KIND = "process"

    def to_obj(self) -> dict:
        o: dict = {"kind": self.KIND}
        _put(o, "rules", {k: v.to_obj() for k, v in self.rules.items()})
        _put(o, "doc", self.doc)
        _put(o, "src", self.src)
        return o

    @classmethod
    def from_obj(cls, name: str, d: dict, r: _Reader, path: str) -> "ProcessDef":
        rules = {
            rn: DfmRule.from_obj(rv, r, f"{path}.rules.{rn}")
            for rn, rv in r.obj(d.get("rules", {}), f"{path}.rules").items()
        }
        doc = r.str_(d, "doc", path)
        src = r.str_(d, "src", path)
        r.unknown_fields(d, ("kind", "rules", "doc", "src"), path)
        return cls(name, rules, doc, src)


Node = Union[Component, Requirement, Analysis, DomainDef, ClaimDef, MaterialDef, ProcessDef]

_KIND_MAP = {
    "component": Component,
    "requirement": Requirement,
    "analysis": Analysis,
    "domain": DomainDef,
    "claim": ClaimDef,
    "material": MaterialDef,
    "process": ProcessDef,
}


# ---------------------------------------------------------------------------
# Connections and the document
# ---------------------------------------------------------------------------


@dataclass
class Connection:
    """An edge between two ports: `from` and `to` are dotted refs component.port.
    Direction is data-flow-free; `from`→`to` follows declared port directions."""

    from_ref: str = ""  # identity
    to_ref: str = ""  # identity
    doc: str = ""  # record
    src: str = ""  # record

    def to_obj(self) -> dict:
        o: dict = {"from": self.from_ref, "to": self.to_ref}
        _put(o, "doc", self.doc)
        _put(o, "src", self.src)
        return o

    @classmethod
    def from_obj(cls, v: Any, r: _Reader, path: str) -> "Connection":
        d = r.obj(v, path)
        from_ref = r.str_(d, "from", path, required=True)
        to_ref = r.str_(d, "to", path, required=True)
        doc = r.str_(d, "doc", path)
        src = r.str_(d, "src", path)
        r.unknown_fields(d, ("from", "to", "doc", "src"), path)
        return cls(from_ref, to_ref, doc, src)


@dataclass
class GraphDoc:
    """The one graph. Names are qualified: requirements live under `req.`,
    libraries under `lib.<libname>.`; project components/analyses are top-level."""

    edition: str = EDITION
    nodes: dict[str, Node] = field(default_factory=dict)
    connections: list[Connection] = field(default_factory=list)

    def to_obj(self) -> dict:
        return {
            "uel_schema": SCHEMA_VERSION,
            "edition": self.edition,
            "nodes": {name: n.to_obj() for name, n in self.nodes.items()},
            **({"connections": [c.to_obj() for c in sorted(self.connections, key=lambda c: (c.from_ref, c.to_ref))]}
               if self.connections else {}),
        }

    def to_canonical(self) -> bytes:
        return canonical_bytes(self.to_obj())

    def to_canonical_str(self) -> str:
        return canonical_str(self.to_obj())

    @classmethod
    def from_obj(cls, obj: Any) -> tuple[Optional["GraphDoc"], list[SchemaError]]:
        r = _Reader()
        d = r.obj(obj, "$")
        if r.errors:
            return None, r.errors
        schema = r.str_(d, "uel_schema", "$", required=True)
        if schema and schema != SCHEMA_VERSION:
            r.err("$.uel_schema", f"unsupported schema version {schema!r} (this kernel: {SCHEMA_VERSION!r})")
        edition = r.str_(d, "edition", "$", default=EDITION)
        nodes: dict[str, Node] = {}
        for name, nv in r.obj(d.get("nodes", {}), "$.nodes").items():
            nd = r.obj(nv, f"$.nodes.{name}")
            kind = r.str_(nd, "kind", f"$.nodes.{name}", required=True)
            klass = _KIND_MAP.get(kind)
            if klass is None:
                r.err(f"$.nodes.{name}.kind", f"unknown node kind {kind!r}")
                continue
            nodes[name] = klass.from_obj(name, nd, r, f"$.nodes.{name}")
        connections = sorted(
            (Connection.from_obj(cv, r, f"$.connections[{i}]")
             for i, cv in enumerate(d.get("connections", []) or [])),
            key=lambda c: (c.from_ref, c.to_ref),
        )
        r.unknown_fields(d, ("uel_schema", "edition", "nodes", "connections"), "$")
        doc = cls(edition, nodes, connections)
        return (doc if not r.errors else None), r.errors

    # -- graph accessors used throughout the kernel --

    def components(self) -> dict[str, Component]:
        return {n: v for n, v in self.nodes.items() if isinstance(v, Component)}

    def analyses(self) -> dict[str, Analysis]:
        return {n: v for n, v in self.nodes.items() if isinstance(v, Analysis)}

    def requirements(self) -> dict[str, Requirement]:
        return {n: v for n, v in self.nodes.items() if isinstance(v, Requirement)}

    def domains(self) -> dict[str, DomainDef]:
        return {n: v for n, v in self.nodes.items() if isinstance(v, DomainDef)}

    def claims(self) -> dict[str, ClaimDef]:
        return {n: v for n, v in self.nodes.items() if isinstance(v, ClaimDef)}

    def materials(self) -> dict[str, MaterialDef]:
        return {n: v for n, v in self.nodes.items() if isinstance(v, MaterialDef)}

    def processes(self) -> dict[str, ProcessDef]:
        return {n: v for n, v in self.nodes.items() if isinstance(v, ProcessDef)}
