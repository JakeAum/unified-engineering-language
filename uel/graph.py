"""The semantic graph — UEL's data model, defined before and independently of syntax.

Kernel kinds (spec §2): component, port, quantity, analysis (the claim node).
Library kinds: domain, claim taxonomy, material, process. Requirements anchor
intents. Every node maps to plain JSON (omit-empty, encoded by `uel.canon`).
Two field classes exist, marked below:

- identity fields — semantic content; participate in hashing;
- record fields — provenance-of-authorship (`src`, doc, judgment prose…), kept
  in the graph but excluded from recipe hashes, so moving a declaration or
  writing judgment never invalidates physics (hashing lands in `uel.hashing`).

Serialization is spec-driven: each class declares SPEC rows
(attr, json_key, kind, emit, *opts) consumed by `_to_obj`/`_read`.
kind: s str · rs required-str · n num · i int · b bool · e enum(allowed,
default) · q quantity · oq optional-quantity · qm quantity-map · o sub-obj
(None reads as default instance) · oo optional sub-obj · om obj-map · ol
sorted obj-list(key) · sm str-map · sl sorted str-list · raw.
emit: "p" omit-empty · "a" always · ("d", V) omit when == V.
Class extras: HEAD constant pairs (e.g. kind); EMPTY_NONE (empty object
serializes as None); _post(kw, r, path) cross-field validation.
Quantity, Uncertainty, and OutputDecl keep hand-written codecs — their
encodings are irregular and they are the hashed hot path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

from .canon import canonical_bytes, canonical_str
from . import EDITION, SCHEMA_VERSION

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
        if v is None: return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self.err(f"{path}.{key}", f"expected number, got {type(v).__name__}")
            return None
        return float(v)

    def int_(self, d: dict, key: str, path: str) -> Optional[int]:
        v = d.get(key, None)
        if v is None: return None
        if isinstance(v, bool) or not isinstance(v, int):
            self.err(f"{path}.{key}", f"expected integer, got {type(v).__name__}")
            return None
        return v

    def bool_(self, d: dict, key: str, path: str, default: bool = False) -> bool:
        v = d.get(key, None)
        if v is None: return default
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
    if value is None or value == "" or value == {} or value == []: return
    d[key] = value

def _str_map(v: Any, r: _Reader, path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if v is None: return out
    for k, s in r.obj(v, path).items():
        if not isinstance(s, str):
            r.err(f"{path}.{k}", f"expected string rationale, got {type(s).__name__}")
            continue
        out[k] = s
    return out

def _str_list(v: Any, r: _Reader, path: str) -> list[str]:
    out: list[str] = []
    if v is None: return out
    if not isinstance(v, list):
        r.err(path, f"expected list of strings, got {type(v).__name__}")
        return out
    for i, s in enumerate(v):
        if not isinstance(s, str):
            r.err(f"{path}[{i}]", f"expected string, got {type(s).__name__}")
        else:
            out.append(s)
    return sorted(set(out))

def _render(v, kind, opts):
    if kind in ("q", "o"): return v.to_obj()
    if kind in ("oo", "oq"): return v.to_obj() if v is not None else None
    if kind in ("qm", "om"): return {k: x.to_obj() for k, x in v.items()}
    if kind == "ol": return [x.to_obj() for x in sorted(v, key=opts[1])]
    if kind == "sl": return sorted(v)
    if kind == "sm": return dict(v)
    return v

def _to_obj(self) -> Any:
    o: dict = dict(getattr(self, "HEAD", ()))
    for attr, key, kind, emit, *opts in self.SPEC:
        rv = _render(getattr(self, attr), kind, opts)
        if emit == "a":
            o[key] = rv
        elif emit == "p":
            _put(o, key, rv)
        elif rv != emit[1]:
            o[key] = rv
    return (o or None) if getattr(self, "EMPTY_NONE", False) else o

def _read(cls, d: dict, r: _Reader, path: str, name: str | None = None):
    kw: dict[str, Any] = {} if name is None else {"name": name}
    keys = []
    for attr, key, kind, _emit, *opts in cls.SPEC:
        keys.append(key)
        sub = f"{path}.{key}"
        if kind == "s":
            kw[attr] = r.str_(d, key, path)
        elif kind == "rs":
            kw[attr] = r.str_(d, key, path, required=True)
        elif kind == "n":
            kw[attr] = r.num(d, key, path)
        elif kind == "i":
            kw[attr] = r.int_(d, key, path)
        elif kind == "b":
            kw[attr] = r.bool_(d, key, path)
        elif kind == "e":
            kw[attr] = r.enum(d, key, path, opts[0], opts[1])
        elif kind == "q":
            kw[attr] = Quantity.from_obj(d.get(key, {}), r, sub)
        elif kind == "oq":
            kw[attr] = Quantity.from_obj(d[key], r, sub) if key in d else None
        elif kind == "qm":
            kw[attr] = {n: Quantity.from_obj(v, r, f"{sub}.{n}")
                        for n, v in r.obj(d.get(key, {}), sub).items()}
        elif kind == "o":
            kw[attr] = opts[0].from_obj(d.get(key), r, sub)
        elif kind == "oo":
            kw[attr] = opts[0].from_obj(d.get(key), r, sub) if d.get(key) is not None else None
        elif kind == "om":
            kw[attr] = {n: opts[0].from_obj(v, r, f"{sub}.{n}")
                        for n, v in r.obj(d.get(key, {}), sub).items()}
        elif kind == "ol":
            kw[attr] = sorted((opts[0].from_obj(v, r, f"{sub}[{i}]")
                               for i, v in enumerate(d.get(key, []) or [])), key=opts[1])
        elif kind == "sm":
            kw[attr] = _str_map(d.get(key), r, sub)
        elif kind == "sl":
            kw[attr] = _str_list(d.get(key), r, sub)
        else:  # raw
            kw[attr] = d.get(key, opts[0] if opts else None)
    r.unknown_fields(d, tuple(keys) + (("kind",) if name is not None else ()), path)
    post = getattr(cls, "_post", None)
    if post:
        post(kw, r, path)
    return cls(**kw)

# Quantity — (value or interval, unit, uncertainty, provenance, confidence)

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
        if self.kind == "none": return None
        o: dict = {"kind": self.kind}
        _put(o, "value", self.value)
        return o

    SPEC = (("kind", "kind", "e", "a", ("none", "abs", "rel", "cal"), "none"),
            ("value", "value", "n", "p"))

    @staticmethod
    def _post(kw, r, path):
        if kw["kind"] in ("abs", "rel") and kw["value"] is None:
            r.err(path, f"uncertainty kind '{kw['kind']}' requires a value")

@dataclass
class Provenance:
    """Where a value came from. kind: declared | measured | vendor | derived |
    estimate (identity-lite, rides along for queries); site/detail/ts are record."""

    kind: str = "declared"
    site: str = ""  # record: file:line or node ref that authored the value
    detail: str = ""  # record: e.g. "datasheet p.3", "test W12 run 3"
    ts: str = ""  # record: ISO timestamp for volatile observations

    EMPTY_NONE = True
    SPEC = (("kind", "kind", "e", ("d", "declared"),
             ("declared", "measured", "vendor", "derived", "estimate"), "declared"),
            ("site", "site", "s", "p"), ("detail", "detail", "s", "p"), ("ts", "ts", "s", "p"))

@dataclass
class Quantity:
    """Every scalar in the graph. Point values are the degenerate case of intervals."""

    value: Value = None  # identity: float, (lo, hi), or None (TBD)
    unit: str = ""  # identity: surface unit expression ("" = dimensionless)
    unc: Uncertainty = field(default_factory=Uncertainty)  # identity
    prov: Provenance = field(default_factory=Provenance)  # kind identity-lite; rest record
    conf: Optional[float] = None  # record: confidence 0..1

    def is_interval(self) -> bool:
        return isinstance(self.value, tuple)

    def to_obj(self) -> dict:
        o: dict = {}
        if self.value is not None:
            o["value"] = [self.value[0], self.value[1]] if isinstance(self.value, tuple) else self.value
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

def _quantities_obj(qs: dict[str, Quantity]) -> dict:
    return {k: v.to_obj() for k, v in qs.items()}

# Envelope (spec §2.5) and the sub-objects nodes are made of

@dataclass
class Predicate:
    """Value predicate over one variable: var in [lo, hi] (either bound optional)."""

    lo: Optional[float] = None  # identity
    hi: Optional[float] = None  # identity
    unit: str = ""  # identity

    SPEC = (("lo", "lo", "n", "p"), ("hi", "hi", "n", "p"), ("unit", "unit", "s", "p"))

    @staticmethod
    def _post(kw, r, path):
        if kw["lo"] is None and kw["hi"] is None:
            r.err(path, "predicate needs at least one bound (lo or hi)")
        if kw["lo"] is not None and kw["hi"] is not None and kw["lo"] > kw["hi"]:
            r.err(path, f"predicate lo {kw['lo']} > hi {kw['hi']}")

@dataclass
class Envelope:
    """predicates: var -> Predicate (SMT-decidable boxes). claims: structural
    claims made (claim -> rationale); requires: claims needed of upstream."""

    predicates: dict[str, Predicate] = field(default_factory=dict)  # identity
    claims: dict[str, str] = field(default_factory=dict)  # identity
    requires: dict[str, str] = field(default_factory=dict)  # identity

    def is_empty(self) -> bool:
        return not (self.predicates or self.claims or self.requires)

    EMPTY_NONE = True
    SPEC = (("predicates", "predicates", "om", "p", Predicate), ("claims", "claims", "sm", "p"),
            ("requires", "requires", "sm", "p"))

@dataclass
class Port:
    domain: str = ""  # identity: e.g. "electrical", "mechanical.translation"
    dir: str = "inout"  # identity: in | out | inout
    attrs: dict[str, Quantity] = field(default_factory=dict)  # identity
    protocol: str = ""  # identity: data ports only
    doc: str = ""  # record

    SPEC = (("domain", "domain", "rs", "a"),
            ("dir", "dir", "e", ("d", "inout"), ("in", "out", "inout"), "inout"),
            ("attrs", "attrs", "qm", "p"), ("protocol", "protocol", "s", "p"),
            ("doc", "doc", "s", "p"))

@dataclass
class Budget:
    op: str = "<="  # identity
    limit: Quantity = field(default_factory=Quantity)  # identity
    at_qty: Optional[int] = None  # identity: cost @ qty N

    SPEC = (("op", "op", "e", "a", ("<=", ">="), "<="), ("limit", "limit", "q", "a"),
            ("at_qty", "at_qty", "i", "p"))

@dataclass
class Contain:
    ref: str = ""  # identity
    count: int = 1  # identity

    SPEC = (("ref", "ref", "rs", "a"), ("count", "count", "i", ("d", 1)))

    @staticmethod
    def _post(kw, r, path):
        if kw["count"] is not None and kw["count"] < 1:
            r.err(f"{path}.count", f"count must be >= 1, got {kw['count']}")
            kw["count"] = 1
        kw["count"] = 1 if kw["count"] is None else kw["count"]

@dataclass
class Datasheet:
    """An imported static reference (spec §7.2): hashed once per revision."""

    source: str = ""  # identity: path or URI of the artifact
    sha256: str = ""  # identity: hash of the artifact revision
    title: str = ""  # record

    EMPTY_NONE = True
    SPEC = (("source", "source", "rs", "p"), ("sha256", "sha256", "s", "p"),
            ("title", "title", "s", "p"))

@dataclass
class Intent:
    ref: str = ""  # identity: requirement or decision this analysis serves
    text: str = ""  # record: the question, restated

    EMPTY_NONE = True
    SPEC = (("ref", "ref", "s", "p"), ("text", "text", "s", "p"))

@dataclass
class Framing:
    """The creative act (spec §3.1): chosen physics model + the envelope fence."""

    model: str = ""  # identity: e.g. "beam.euler_bernoulli"
    envelope: Envelope = field(default_factory=Envelope)  # identity

    EMPTY_NONE = True
    SPEC = (("model", "model", "s", "p"), ("envelope", "envelope", "o", "p", Envelope))

@dataclass
class Core:
    """The executable recipe (spec §3.2). Python cores are opaque (file content
    is identity; path is not). v0.2 expr/stub cores are transparent: the
    canonical body in `text` IS the content. v0.3: pinned `tools` and the
    wrapped module's `interface` manifest are identity too (ADR-0008)."""

    lang: str = "python"  # identity: python | expr | stub
    path: str = ""  # record-as-locator
    text: str = ""  # identity: canonical expr/stub body
    tools: dict[str, str] = field(default_factory=dict)  # identity: tool -> version pin
    interface: Optional[Datasheet] = None  # identity

    EMPTY_NONE = True
    SPEC = (("lang", "lang", "raw", ("d", "python"), "python"), ("path", "path", "s", "p"),
            ("text", "text", "s", "p"), ("tools", "tools", "sm", "p"),
            ("interface", "interface", "oo", "p", Datasheet))

    @staticmethod
    def _post(kw, r, path):
        if not isinstance(kw["lang"], str):
            r.err(f"{path}.lang", f"expected string, got {type(kw['lang']).__name__}")
            kw["lang"] = "python"

@dataclass
class OutputDecl:
    unit: str = ""  # identity
    unc: bool = False  # identity: output carries uncertainty
    artifact: bool = False  # identity: file artifact rather than quantity
    # v0.2 (ADR-0007): the acceptance bound this output must satisfy, re-verdicted
    # against the lock. Exactly one of target_ref/target_value when target_op set.
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
class Verify:
    """A verification contract (v0.3, ADR-0008): a machine-checkable reason to
    believe this analysis. 'against' = lock-vs-lock cross-check; 'monotone' =
    build-time perturbation probe; 'case' = golden input file re-proven each
    build. Empty tol_unit means relative (tol is a fraction); else absolute in
    that unit (`within 0.5 dB`)."""

    kind: str = "against"  # identity: against | monotone | case
    output: str = ""  # identity
    ref: str = ""  # identity (against)
    known: str = ""  # identity (monotone)
    direction: str = ""  # identity (monotone): rising | falling
    path: str = ""  # identity (case)
    tol: Optional[float] = None  # identity
    tol_unit: str = ""  # identity

    SPEC = (("kind", "kind", "e", "a", ("against", "monotone", "case"), "against"),
            ("output", "output", "s", "p"), ("ref", "ref", "s", "p"),
            ("known", "known", "s", "p"), ("direction", "direction", "s", "p"),
            ("path", "path", "s", "p"), ("tol", "tol", "n", "p"),
            ("tol_unit", "tol_unit", "s", "p"))

    @staticmethod
    def _post(kw, r, path):
        if kw["direction"] and kw["direction"] not in ("rising", "falling"):
            r.err(f"{path}.direction", f"expected rising|falling, got {kw['direction']!r}")
            kw["direction"] = ""

    def sort_key(self) -> tuple:
        return (self.kind, self.output, self.ref, self.known, self.path)

@dataclass
class Judgment:
    """The sense-making, recorded with residual doubts (spec §3.1). Record
    fields: editing judgment prose never re-runs physics."""

    status: str = "pending"  # pending | accepted | rejected | superseded
    text: str = ""
    doubts: str = ""

    EMPTY_NONE = True
    SPEC = (("status", "status", "e", ("d", "pending"),
             ("pending", "accepted", "rejected", "superseded"), "pending"),
            ("text", "text", "s", "p"), ("doubts", "doubts", "s", "p"))

@dataclass
class EffortFlow:
    name: str = ""  # identity: attribute name, e.g. "voltage"
    unit: str = ""  # identity: canonical unit, e.g. "V"

    EMPTY_NONE = True
    SPEC = (("name", "name", "s", "p"), ("unit", "unit", "s", "p"))

@dataclass
class DfmRule:
    """One statically checkable claim of shop knowledge (spec §7.1)."""

    feature: str = ""  # identity
    op: str = ">="  # identity: >= | <= | forbid | require
    limit: Optional[Quantity] = None  # identity
    message: str = ""  # record (the why; shown in diagnostics)

    SPEC = (("feature", "feature", "rs", "a"),
            ("op", "op", "e", "a", (">=", "<=", "forbid", "require"), ">="),
            ("limit", "limit", "oq", "p"), ("message", "message", "s", "p"))

    @staticmethod
    def _post(kw, r, path):
        if kw["op"] in (">=", "<=") and kw["limit"] is None:
            r.err(path, f"rule op '{kw['op']}' requires a limit quantity")

@dataclass
class Connection:
    """An edge between two ports (`component.port` refs)."""

    from_ref: str = ""  # identity
    to_ref: str = ""  # identity
    doc: str = ""  # record
    src: str = ""  # record

    SPEC = (("from_ref", "from", "rs", "a"), ("to_ref", "to", "rs", "a"),
            ("doc", "doc", "s", "p"), ("src", "src", "s", "p"))

# Nodes

_RECORD_TAIL = (("doc", "doc", "s", "p"), ("src", "src", "s", "p"))

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
    process: str = ""  # identity: manufacturing process ref (activates DFM)
    material: str = ""  # identity
    geometry: str = ""  # identity: geometry analysis node producing this shape
    datasheet: Optional[Datasheet] = None  # identity
    doc: str = ""  # record
    src: str = ""  # record: file:line of declaration

    KIND = "component"
    HEAD = (("kind", "component"),)
    SPEC = (("level", "level", "e", "a", ("functional", "behavioral", "physical"), "functional"),
            ("ports", "ports", "om", "p", Port), ("quantities", "quantities", "qm", "p"),
            ("budgets", "budgets", "om", "p", Budget), ("envelope", "envelope", "o", "p", Envelope),
            ("contains", "contains", "ol", "p", Contain, lambda c: c.ref),
            ("realizes", "realizes", "s", "p"), ("process", "process", "s", "p"),
            ("material", "material", "s", "p"), ("geometry", "geometry", "s", "p"),
            ("datasheet", "datasheet", "oo", "p", Datasheet)) + _RECORD_TAIL

@dataclass
class Requirement:
    name: str = ""
    text: str = ""  # identity (the requirement IS its text)
    quantities: dict[str, Quantity] = field(default_factory=dict)  # identity
    doc: str = ""  # record
    src: str = ""  # record

    KIND = "requirement"
    HEAD = (("kind", "requirement"),)
    SPEC = (("text", "text", "s", "p"), ("quantities", "quantities", "qm", "p")) + _RECORD_TAIL

@dataclass
class Analysis:
    """Engineering's unit of work: an argument that a claim about the system is
    justified (spec §3). akind 'geometry' additionally must assert topology."""

    name: str = ""
    akind: str = "analysis"  # identity: analysis | geometry
    intent: Intent = field(default_factory=Intent)  # identity (ref); text record
    framing: Framing = field(default_factory=Framing)  # identity
    knowns: dict[str, str] = field(default_factory=dict)  # identity: local -> graph ref
    params: dict[str, Quantity] = field(default_factory=dict)  # identity
    core: Core = field(default_factory=Core)  # identity via content
    outputs: dict[str, OutputDecl] = field(default_factory=dict)  # identity
    verifies: list[Verify] = field(default_factory=list)  # identity (v0.3)
    judgment: Judgment = field(default_factory=Judgment)  # record
    doc: str = ""  # record
    src: str = ""  # record

    KIND = "analysis"
    HEAD = (("kind", "analysis"),)
    SPEC = (("akind", "akind", "e", ("d", "analysis"), ("analysis", "geometry"), "analysis"),
            ("intent", "intent", "o", "p", Intent), ("framing", "framing", "o", "p", Framing),
            ("knowns", "knowns", "sm", "p"), ("params", "params", "qm", "p"),
            ("core", "core", "o", "p", Core), ("outputs", "outputs", "om", "p", OutputDecl),
            ("verifies", "verifies", "ol", "p", Verify, Verify.sort_key),
            ("judgment", "judgment", "o", "p", Judgment)) + _RECORD_TAIL

@dataclass
class DomainDef:
    """A port domain (spec §2.2): an effort/flow pair whose product is power,
    or a material/data domain. Library, not kernel."""

    name: str = ""
    dclass: str = "power"  # identity: power | material | data
    effort: EffortFlow = field(default_factory=EffortFlow)  # identity
    flow: EffortFlow = field(default_factory=EffortFlow)  # identity
    doc: str = ""  # record
    src: str = ""  # record

    KIND = "domain"
    HEAD = (("kind", "domain"),)
    SPEC = (("dclass", "dclass", "e", "a", ("power", "material", "data"), "power"),
            ("effort", "effort", "o", "p", EffortFlow),
            ("flow", "flow", "o", "p", EffortFlow)) + _RECORD_TAIL

    @staticmethod
    def _post(kw, r, path):
        if kw["dclass"] == "power" and (not kw["effort"].name or not kw["flow"].name):
            r.err(path, "power domain requires both effort and flow definitions")

@dataclass
class ClaimDef:
    """A structural claim in the assumption taxonomy (spec §2.5), with
    hand-authored entailment/exclusion rules."""

    name: str = ""
    entails: list[str] = field(default_factory=list)  # identity
    excludes: list[str] = field(default_factory=list)  # identity
    doc: str = ""  # record
    src: str = ""  # record

    KIND = "claim"
    HEAD = (("kind", "claim"),)
    SPEC = (("entails", "entails", "sl", "p"), ("excludes", "excludes", "sl", "p")) + _RECORD_TAIL

@dataclass
class MaterialDef:
    name: str = ""
    quantities: dict[str, Quantity] = field(default_factory=dict)  # identity
    doc: str = ""  # record
    src: str = ""  # record

    KIND = "material"
    HEAD = (("kind", "material"),)
    SPEC = (("quantities", "quantities", "qm", "p"),) + _RECORD_TAIL

@dataclass
class ProcessDef:
    """A manufacturing process: a DFM ruleset activated at binding (spec §7.1)."""

    name: str = ""
    rules: dict[str, DfmRule] = field(default_factory=dict)  # identity
    doc: str = ""  # record
    src: str = ""  # record

    KIND = "process"
    HEAD = (("kind", "process"),)
    SPEC = (("rules", "rules", "om", "p", DfmRule),) + _RECORD_TAIL

Node = Union[Component, Requirement, Analysis, DomainDef, ClaimDef, MaterialDef, ProcessDef]

_KIND_MAP = {"component": Component, "requirement": Requirement, "analysis": Analysis,
             "domain": DomainDef, "claim": ClaimDef, "material": MaterialDef,
             "process": ProcessDef}

_SUB_DEFAULT = (Uncertainty, Provenance, Envelope, Intent, Framing, Core, Judgment, EffortFlow)
_SUB_PLAIN = (Predicate, Port, Budget, Contain, DfmRule, Verify, Connection)

def _wire_codecs() -> None:
    """Attach generated codecs. Node classes read as (name, d, r, path); plain
    sub-objects as (v, r, path); default-able sub-objects map None -> default;
    Datasheet maps None -> None. Hand-written to_obj methods are kept."""
    def node_reader(cls):
        return staticmethod(lambda name, d, r, path: _read(cls, d, r, path, name=name))

    def plain_reader(cls):
        return staticmethod(lambda v, r, path: _read(cls, r.obj(v, path), r, path))

    def default_reader(cls):
        return staticmethod(lambda v, r, path: cls() if v is None
                            else _read(cls, r.obj(v, path), r, path))

    for c in _KIND_MAP.values():
        c.to_obj, c.from_obj = _to_obj, node_reader(c)
    for c in _SUB_PLAIN:
        c.to_obj, c.from_obj = _to_obj, plain_reader(c)
    for c in _SUB_DEFAULT:
        if "to_obj" not in c.__dict__:
            c.to_obj = _to_obj
        c.from_obj = default_reader(c)
    Datasheet.to_obj = _to_obj
    Datasheet.from_obj = staticmethod(lambda v, r, path: None if v is None
                                      else _read(Datasheet, r.obj(v, path), r, path))

_wire_codecs()

@dataclass
class GraphDoc:
    """The one graph. Requirements live under `req.`, libraries under
    `lib.<libname>.`; project components/analyses are top-level."""

    edition: str = EDITION
    nodes: dict[str, Node] = field(default_factory=dict)
    connections: list[Connection] = field(default_factory=list)

    def to_obj(self) -> dict:
        return {"uel_schema": SCHEMA_VERSION, "edition": self.edition,
                "nodes": {name: n.to_obj() for name, n in self.nodes.items()},
                **({"connections": [c.to_obj() for c in
                                    sorted(self.connections, key=lambda c: (c.from_ref, c.to_ref))]}
                   if self.connections else {})}

    def to_canonical(self) -> bytes:
        return canonical_bytes(self.to_obj())

    def to_canonical_str(self) -> str:
        return canonical_str(self.to_obj())

    @classmethod
    def from_obj(cls, obj: Any) -> tuple[Optional["GraphDoc"], list[SchemaError]]:
        r = _Reader()
        d = r.obj(obj, "$")
        if r.errors: return None, r.errors
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
            key=lambda c: (c.from_ref, c.to_ref))
        r.unknown_fields(d, ("uel_schema", "edition", "nodes", "connections"), "$")
        doc = cls(edition, nodes, connections)
        return (doc if not r.errors else None), r.errors

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
