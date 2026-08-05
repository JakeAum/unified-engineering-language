"""The surface AST — what the parser produces and the formatter re-prints.

Deliberately close to the grammar and carrying spans everywhere; the resolver turns
this into the semantic graph (`uel.graph`). `fingerprint()` gives a span-free,
comment-free structural identity used by conformance to prove the formatter
preserves meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

from .diagnostics import Span
from .lexer import Comment

@dataclass
class DottedRef:
    parts: list[str]
    span: Span

    @property
    def text(self) -> str:
        return ".".join(self.parts)

@dataclass
class UncTail:
    """± 10 g | ± 5 % | ± cal | bare ± (outputs only)."""

    kind: str  # abs | rel | cal | bare
    value: Optional[float] = None
    unit: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class QNumber:
    value: float
    unit: str
    unit_span: Span
    unc: Optional[UncTail] = None
    span: Span = field(default_factory=Span)

@dataclass
class QInterval:
    lo: float
    hi: float
    unit: str
    unit_span: Span
    unc: Optional[UncTail] = None
    span: Span = field(default_factory=Span)
    unit_inside: bool = True  # [0, 12 kN] vs [0, 12] kN — formatter canonicalizes to inside

QExpr = Union[QNumber, QInterval, DottedRef]

@dataclass
class QuantityDecl:
    name: str
    expr: QExpr
    prov_detail: str = ""  # `from "datasheet p.3"`
    span: Span = field(default_factory=Span)

@dataclass
class PortAttr:
    name: str
    expr: QExpr
    prov_detail: str = ""  # `from "datasheet p.2"`
    span: Span = field(default_factory=Span)

@dataclass
class PortDecl:
    name: str
    domain: DottedRef
    dir: str = ""  # "" = inout default
    protocol: str = ""
    attrs: list[PortAttr] = field(default_factory=list)
    doc: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class BudgetDecl:
    name: str
    op: str  # <= | >=
    expr: QExpr
    at_qty: Optional[int] = None
    span: Span = field(default_factory=Span)

@dataclass
class ContainsDecl:
    ref: DottedRef
    count: int = 1
    span: Span = field(default_factory=Span)

@dataclass
class EnvPredicate:
    var: str
    lo: Optional[float]
    hi: Optional[float]
    unit: str
    unit_span: Span
    interval_form: bool  # `x in [lo, hi]` vs one-sided `x <= n`
    op: str = ""  # one-sided form only: <=, >=, <, >
    span: Span = field(default_factory=Span)

@dataclass
class EnvClaim:
    keyword: str  # assume | require
    claim: str
    rationale: str = ""
    span: Span = field(default_factory=Span)

EnvItem = Union[EnvPredicate, EnvClaim]

@dataclass
class EnvelopeBlock:
    items: list[EnvItem] = field(default_factory=list)
    span: Span = field(default_factory=Span)

@dataclass
class ComponentDecl:
    name: str
    level: str
    ports: list[PortDecl] = field(default_factory=list)
    quantities: list[QuantityDecl] = field(default_factory=list)
    budgets: list[BudgetDecl] = field(default_factory=list)
    envelope: Optional[EnvelopeBlock] = None
    contains: list[ContainsDecl] = field(default_factory=list)
    doc: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class DatasheetRef:
    source: str
    sha256: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class BindingDecl:
    source: DottedRef
    target: str
    process: Optional[DottedRef] = None
    material: Optional[DottedRef] = None
    geometry_code: str = ""  # `geometry code "path.py"` sugar
    geometry_ref: Optional[DottedRef] = None  # `geometry NodeName` explicit form
    datasheet: Optional[DatasheetRef] = None
    quantities: list[QuantityDecl] = field(default_factory=list)
    ports: list[PortDecl] = field(default_factory=list)
    envelope: Optional[EnvelopeBlock] = None
    doc: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class IntentDecl:
    ref: DottedRef
    text: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class FramingDecl:
    model: Optional[DottedRef] = None
    claims: list[EnvClaim] = field(default_factory=list)  # assume/require outside envelope
    # v0.6: hazard accounting against the registered model's hazard list —
    # covers (keyword "covers", no rationale) and waive (rationale required)
    covers: list[EnvClaim] = field(default_factory=list)
    waives: list[EnvClaim] = field(default_factory=list)
    envelope: Optional[EnvelopeBlock] = None
    span: Span = field(default_factory=Span)

@dataclass
class KnownDecl:
    name: str
    ref: DottedRef
    span: Span = field(default_factory=Span)

@dataclass
class OutputDeclA:
    name: str
    unit: str = ""  # "dimensionless" normalized to ""
    unit_span: Span = field(default_factory=Span)
    unc: bool = False
    artifact: bool = False
    target_op: str = ""  # v0.2: "" | ">=" | "<="
    target_expr: Optional[QExpr] = None  # literal or reference the output must satisfy
    span: Span = field(default_factory=Span)

@dataclass
class JudgmentDecl:
    status: str = "pending"
    text: str = ""
    doubts: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class VerifyDecl:
    """v0.3 (ADR-0008): a machine-checkable reason to believe an opaque core.

    kind 'against': output cross-checked vs another node's value, within tol.
    kind 'monotone': output must move the declared direction when an input rises.
    kind 'case': re-run the core on a golden input file; expected outputs within tol.
    """

    kind: str  # against | monotone | case
    output: str = ""
    ref: Optional[DottedRef] = None  # against
    known: str = ""  # monotone: the input to perturb
    direction: str = ""  # monotone: rising | falling
    path: str = ""  # case: JSON file with inputs + expect
    tol: Optional[float] = None  # against/case (fraction when relative)
    tol_unit: str = ""  # "" = relative (%); else absolute in this unit
    tol_unit_span: Span = field(default_factory=Span)
    span: Span = field(default_factory=Span)

@dataclass
class CoreToolDecl:
    """A pinned external tool a python core invokes: identity, not prose."""

    name: str
    version: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class AnalysisDecl:
    name: str
    akind: str = "analysis"  # analysis | geometry
    intent: Optional[IntentDecl] = None
    framing: Optional[FramingDecl] = None
    knowns: list[KnownDecl] = field(default_factory=list)
    params: list[QuantityDecl] = field(default_factory=list)
    core_lang: str = ""
    core_path: str = ""
    core_body: list = field(default_factory=list)  # v0.2: expr.ExprStmt for expr/stub cores
    core_tools: list[CoreToolDecl] = field(default_factory=list)  # v0.3: pinned externals
    core_interface_path: str = ""  # v0.3: black-box interface manifest (e.g. FMU XML)
    core_interface_sha: str = ""
    verifies: list[VerifyDecl] = field(default_factory=list)  # v0.3
    outputs: list[OutputDeclA] = field(default_factory=list)
    judgment: Optional[JudgmentDecl] = None
    doc: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class ConnectDecl:
    from_ref: DottedRef
    to_ref: DottedRef
    span: Span = field(default_factory=Span)

@dataclass
class RequirementDecl:
    name: str
    text: str = ""
    quantities: list[QuantityDecl] = field(default_factory=list)
    doc: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class DomainDecl:
    name: str
    dclass: str = "power"
    effort_name: str = ""
    effort_unit: str = ""
    flow_name: str = ""
    flow_unit: str = ""
    doc: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class ClaimDecl:
    name: str
    entails: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    doc: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class MaterialDecl:
    name: str
    quantities: list[QuantityDecl] = field(default_factory=list)
    doc: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class RuleDecl:
    name: str
    feature: str
    op: str  # >= | <= | forbid | require
    limit: Optional[QExpr] = None
    message: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class ProcessDecl:
    name: str
    rules: list[RuleDecl] = field(default_factory=list)
    doc: str = ""
    span: Span = field(default_factory=Span)

@dataclass
class ModelDecl:
    """v0.6: a registered physics model with its hazard list — the failure modes
    the model structurally cannot see, each with the reason it kills."""

    name: str  # dotted, e.g. beam.euler_bernoulli
    hazards: list[EnvClaim] = field(default_factory=list)  # keyword "hazard"
    doc: str = ""
    span: Span = field(default_factory=Span)

Item = Union[
    RequirementDecl, ComponentDecl, BindingDecl, AnalysisDecl, ConnectDecl,
    DomainDecl, ClaimDecl, MaterialDecl, ProcessDecl, ModelDecl,
]

@dataclass
class ASTFile:
    path: str
    items: list[Item] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)

# Structural fingerprint (span- and comment-free) for formatter conformance

def _fp(v: object) -> object:
    from dataclasses import fields as dc_fields, is_dataclass

    if isinstance(v, Span): return None
    if is_dataclass(v) and not isinstance(v, type):
        if isinstance(v, Comment): return None
        out = {"__t": type(v).__name__}
        for f in dc_fields(v):
            if f.name in ("span", "unit_span", "comments", "unit_inside"): continue
            out[f.name] = _fp(getattr(v, f.name))
        return out
    if isinstance(v, list): return [_fp(x) for x in v]
    return v

def fingerprint(ast: ASTFile) -> str:
    """Stable structural identity of a file's meaning (not its layout)."""
    import json

    return json.dumps({"items": [_fp(i) for i in ast.items]}, sort_keys=True)
