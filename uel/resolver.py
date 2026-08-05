"""Resolution: surface ASTs → the semantic graph (uel.graph.GraphDoc).

Responsibilities:
- namespace assembly (stdlib + project lib under `lib.*`, requirements under `req.`)
- duplicate detection, reference resolution with did-you-mean fixes
- binding sugar: `binding F -> p : physical {…}` produces a physical component
  with `realizes`, and `geometry code "path"` materializes a geometry analysis
  node `<p>_geom` whose params are the binding's quantities
- units and dimensions checking (every literal, port attr vs domain, budgets,
  envelope predicates, domain effort×flow=power)
- provenance stamping (site = file:line; `from "…"` → vendor detail)
- reference-cycle detection over knowns/containment

Member reference forms resolved for knowns:
    req.NAME.quantity
    lib.ns.NAME.quantity
    component.quantity | component.port.attr | component.<geometry-output>
    analysis.outputs.name        (the `outputs.` segment is required)
Component geometry-output fallthrough rewrites to the canonical
`<geom>.outputs.<name>` form, so the stored graph is fully explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import get_close_matches

from . import expr as X
from . import graph as G
from . import uast as A
from .diagnostics import Bag, Fix, Span
from .project import Project, SourceFile
from .parser import parse_text
from .units import (
    DIMENSIONLESS, UnitError, parse_unit, dim_name, type_name,
    D_MASS, D_CURRENCY, D_TIME, D_POWER, dim_mul,
)

@dataclass
class ResolvedRef:
    """A value reference resolved to its producing node + member path."""

    target: str  # canonical ref string
    node: str  # producing node name
    unit: str  # declared unit text of the referenced value ("" = dimensionless)
    kind: str  # "quantity" | "port_attr" | "output"
    quantity: G.Quantity | None = None  # for statically-known values

@dataclass
class Resolution:
    doc: G.GraphDoc
    project: Project
    asts: list[A.ASTFile] = field(default_factory=list)
    # every knowns/ref edge resolved: (consumer node, local name) -> ResolvedRef
    known_refs: dict[tuple[str, str], ResolvedRef] = field(default_factory=dict)
    # v0.2: parsed expr/stub core programs, keyed by analysis name
    expr_programs: dict[str, list[X.ExprStmt]] = field(default_factory=dict)
    # v0.2: resolved output-target references: (node, output) -> ResolvedRef
    target_refs: dict[tuple[str, str], ResolvedRef] = field(default_factory=dict)
    # v0.3: resolved verify-against references: (node, verify index) -> ResolvedRef
    verify_refs: dict[tuple[str, int], ResolvedRef] = field(default_factory=dict)

_BUDGET_DIMS = {"mass": D_MASS, "unit_cost": D_CURRENCY, "lead_time": D_TIME}

class Resolver:
    def __init__(self, project: Project, bag: Bag):
        self.project = project
        self.bag = bag
        self.doc = G.GraphDoc(edition=project.edition)
        self.decl_spans: dict[str, Span] = {}
        # fine-grained spans for cross-reference diagnostics: key -> Span
        # ("known", node, local) | ("port", node, port) | ("intent", node)
        # ("contains", node, ref) | ("process"/"material"/"geometry"/"realizes", node)
        # ("connfrom"/"connto", index)
        self.member_spans: dict[tuple, Span] = {}
        self.asts: list[A.ASTFile] = []
        self.res = Resolution(self.doc, project, self.asts)

    def mspan(self, *key, default: Span | None = None) -> Span:
        return self.member_spans.get(key, default if default is not None else Span())

    # ------------------------------------------------------------------
    def run(self) -> Resolution:
        parsed: list[tuple[SourceFile, A.ASTFile]] = []
        for sf in self.project.files:
            ast = parse_text(sf.text, sf.rel, self.bag)
            parsed.append((sf, ast))
            self.asts.append(ast)
        # Pass A: declare all names
        for sf, ast in parsed:
            ns = sf.namespace.removeprefix("stdlib:")
            for item in ast.items:
                self.declare_item(item, ns)
        # Pass B: build nodes
        for sf, ast in parsed:
            ns = sf.namespace.removeprefix("stdlib:")
            for item in ast.items:
                self.build_item(item, ns, sf.rel)
        # Pass C: cross-node resolution and cycles
        self.resolve_all_refs()
        self.check_cycles()
        # Pass D (v0.2): type-check expr/stub core bodies against resolved knowns
        self.check_expr_programs()
        return self.res

    # ------------------------------------------------------------------
    # naming

    def qualify(self, item: A.Item, ns: str) -> str:
        if isinstance(item, A.RequirementDecl):
            base = f"req.{item.name}"
        elif isinstance(item, A.BindingDecl):
            base = item.target
        else:
            base = getattr(item, "name", "?")
        return f"{ns}.{base}" if ns else base

    def declare(self, name: str, span: Span) -> bool:
        if name in ("req", "lib") or name.startswith(("req.req", "lib.lib")):
            self.bag.error(
                "UEL0201",
                f"'{name}' collides with a reserved namespace ('req.', 'lib.')",
                span,
                reason="requirements live under req.*, libraries under lib.*; a node with that bare name would shadow them",
            )
            return False
        if name in self.decl_spans:
            self.bag.error(
                "UEL0201",
                f"'{name}' is defined more than once",
                span,
                reason="one graph, one name per node; merge or rename",
                related=[("first defined here", self.decl_spans[name])],
            )
            return False
        self.decl_spans[name] = span
        return True

    def declare_item(self, item: A.Item, ns: str) -> None:
        if isinstance(item, A.ConnectDecl): return
        name = self.qualify(item, ns)
        self.declare(name, item.span)
        if isinstance(item, A.BindingDecl) and item.geometry_code:
            self.declare(f"{name}_geom", item.span)

    # ------------------------------------------------------------------
    # quantities and envelopes

    def unit_of(self, text: str, span: Span) -> str:
        """Validate a unit expression; return canonical text ('' if invalid/empty)."""
        if not text: return ""
        try:
            return parse_unit(text).text
        except UnitError as e:
            if "affine" in str(e):
                self.bag.error(
                    "UEL0303", str(e), span,
                    reason="affine units (degC, degF) are standalone-only: 'K/W' means something, 'degC/W' does not",
                    fix=Fix(hint="convert to K to compose (K and degC have equal increments)"),
                )
                return ""
            fix = None
            if e.suggestion:
                fix = Fix(hint=f"did you mean '{e.suggestion}'?", replace=e.suggestion, span=span)
            self.bag.error("UEL0301", str(e), span, fix=fix,
                           reason="units are mandatory and checked (spec §2.4)")
            return ""

    def quantity(self, expr: A.QExpr, file: str, prov_detail: str = "") -> G.Quantity | None:
        """Literal QExpr → Quantity. Returns None for reference-valued expressions."""
        if isinstance(expr, A.DottedRef): return None
        unit = self.unit_of(expr.unit, expr.unit_span)
        unc = G.Uncertainty()
        if expr.unc is not None:
            u = expr.unc
            if u.kind == "abs":
                unc_unit = self.unit_of(u.unit, u.span) if u.unit else unit
                if u.unit and unit:
                    try:
                        du, dv = parse_unit(unc_unit), parse_unit(unit)
                        # a delta between levels of any one reference is a ratio,
                        # so ± on a level value is written in dB (or, loosely,
                        # in the value's own level unit — the difference IS dB)
                        ok = du.vtype == dv.vtype or (
                            du.level and dv.level and du.dim == DIMENSIONLESS
                        )
                        if not ok:
                            self.bag.error(
                                "UEL0302",
                                f"uncertainty unit '{unc_unit}' ({type_name(*du.vtype)}) does not "
                                f"match value unit '{unit}' ({type_name(*dv.vtype)})",
                                u.span,
                                reason="uncertainty on a level is a dB delta ('± 1.5 dB'); "
                                       "uncertainty on a linear value shares its dimension"
                                if dv.level or du.level else
                                "uncertainty and value must share a dimension",
                            )
                    except UnitError:
                        pass
                # normalize absolute uncertainty into the value's unit
                value = u.value or 0.0
                if u.unit and unit and unc_unit:
                    try:
                        du, dv = parse_unit(unc_unit), parse_unit(unit)
                        if du.dim == dv.dim and not du.affine and not dv.affine \
                                and du.level == dv.level:
                            value = value * du.factor / dv.factor
                    except UnitError:
                        pass
                unc = G.Uncertainty("abs", value)
            elif u.kind == "rel":
                unc = G.Uncertainty("rel", u.value)
            elif u.kind in ("cal", "bare"):
                unc = G.Uncertainty("cal")
        prov = G.Provenance(site=f"{file}:{expr.span.line}")
        if prov_detail:
            prov.kind = "vendor"
            prov.detail = prov_detail
        value: G.Value
        if isinstance(expr, A.QInterval):
            value = (expr.lo, expr.hi)
        else:
            value = expr.value
        return G.Quantity(value, unit, unc, prov)

    def quantity_decls(self, decls: list[A.QuantityDecl], file: str, owner: str) -> dict[str, G.Quantity]:
        out: dict[str, G.Quantity] = {}
        for d in decls:
            if d.name in out:
                self.bag.error("UEL0106", f"'{d.name}' declared twice in {owner}", d.span)
                continue
            q = self.quantity(d.expr, file, d.prov_detail)
            if q is None:
                self.bag.error(
                    "UEL0107",
                    f"'{d.name}' is assigned a reference; v0.1 quantities are literals",
                    d.span,
                    reason="references flow through analysis knowns ('name <- ref'), which carry staleness; aliasing values would hide dependencies",
                )
                continue
            out[d.name] = q
        return out

    def envelope(self, blk: A.EnvelopeBlock | None, extra_claims: list[A.EnvClaim], file: str) -> G.Envelope:
        env = G.Envelope()
        items: list[A.EnvItem] = list(blk.items) if blk else []
        for c in extra_claims:
            items.append(c)
        for it in items:
            if isinstance(it, A.EnvPredicate):
                if it.var in env.predicates:
                    self.bag.error("UEL0106", f"envelope variable '{it.var}' fenced twice", it.span)
                    continue
                unit = self.unit_of(it.unit, it.unit_span)
                env.predicates[it.var] = G.Predicate(it.lo, it.hi, unit)
            else:
                target = env.claims if it.keyword == "assume" else env.requires
                if it.claim in target:
                    self.bag.error("UEL0106", f"claim '{it.claim}' declared twice", it.span)
                    continue
                target[it.claim] = it.rationale
                self.check_claim_known(it.claim, it.span)
        return env

    def check_claim_known(self, claim: str, span: Span) -> None:
        if claim in self.decl_spans or f"lib.claims.{claim}" in self.decl_spans: return
        known = sorted(
            n.removeprefix("lib.claims.") for n in self.decl_spans if n.startswith("lib.claims.")
        )
        close = get_close_matches(claim, known, 1, 0.6)
        self.bag.warning(
            "UEL0504",
            f"structural claim '{claim}' is not in the taxonomy",
            span,
            reason="declared-but-unchecked beats undeclared (spec §2.5): the claim is recorded, but no entailment checking will cover it",
            fix=Fix(hint=f"did you mean '{close[0]}'? Otherwise add 'claim {claim} {{ }}' to a project lib"
                    if close else f"add 'claim {claim} {{ }}' to a project lib to enter the taxonomy",
                    replace=close[0] if close else None, span=span),
        )

    # ------------------------------------------------------------------
    # node building

    def build_item(self, item: A.Item, ns: str, file: str) -> None:
        if isinstance(item, A.ComponentDecl):
            self.build_component(item, ns, file)
        elif isinstance(item, A.BindingDecl):
            self.build_binding(item, ns, file)
        elif isinstance(item, A.AnalysisDecl):
            self.build_analysis(item, ns, file)
        elif isinstance(item, A.RequirementDecl):
            self.build_requirement(item, ns, file)
        elif isinstance(item, A.ConnectDecl):
            idx = len(self.doc.connections)
            self.member_spans[("connfrom", idx)] = item.from_ref.span
            self.member_spans[("connto", idx)] = item.to_ref.span
            self.doc.connections.append(
                G.Connection(item.from_ref.text, item.to_ref.text, src=f"{file}:{item.span.line}")
            )
        elif isinstance(item, A.DomainDecl):
            self.build_domain(item, ns, file)
        elif isinstance(item, A.ClaimDecl):
            name = self.qualify(item, ns)
            self.doc.nodes[name] = G.ClaimDef(
                name, sorted(set(item.entails)), sorted(set(item.excludes)), item.doc,
                f"{file}:{item.span.line}",
            )
        elif isinstance(item, A.MaterialDecl):
            name = self.qualify(item, ns)
            self.doc.nodes[name] = G.MaterialDef(
                name, self.quantity_decls(item.quantities, file, f"material {item.name}"),
                item.doc, f"{file}:{item.span.line}",
            )
        elif isinstance(item, A.ProcessDecl):
            self.build_process(item, ns, file)

    def build_port(self, p: A.PortDecl, file: str, owner: str) -> G.Port:
        attrs: dict[str, G.Quantity] = {}
        for a in p.attrs:
            if a.name in attrs:
                self.bag.error("UEL0106", f"port attribute '{a.name}' declared twice", a.span)
                continue
            q = self.quantity(a.expr, file, a.prov_detail)
            if q is None:
                self.bag.error("UEL0107", f"port attribute '{a.name}' must be a literal quantity", a.span)
                continue
            attrs[a.name] = q
        return G.Port(p.domain.text, p.dir or "inout", attrs, p.protocol, p.doc)

    def _check_member_collisions(self, name: str, ports, quantities, budgets) -> None:
        """Ports, quantities, and budgets share the component's member namespace
        (dotted refs must be unambiguous)."""
        seen: dict[str, tuple[str, Span]] = {}
        for kind, decls in (("port", ports), ("quantity", quantities), ("budget", budgets)):
            for d in decls:
                if d.name in seen:
                    okind, ospan = seen[d.name]
                    self.bag.error(
                        "UEL0201",
                        f"'{name}.{d.name}' is both a {okind} and a {kind}",
                        d.span,
                        reason="members share one namespace: 'comp.member' must resolve unambiguously",
                        related=[(f"{okind} declared here", ospan)],
                    )
                else:
                    seen[d.name] = (kind, d.span)

    def build_component(self, c: A.ComponentDecl, ns: str, file: str) -> None:
        name = self.qualify(c, ns)
        self._check_member_collisions(name, c.ports, c.quantities, c.budgets)
        for p in c.ports:
            self.member_spans[("port", name, p.name)] = p.domain.span
        for cd in c.contains:
            self.member_spans[("contains", name, cd.ref.text)] = cd.ref.span
        comp = G.Component(
            name=name,
            level=c.level,
            ports={p.name: self.build_port(p, file, name) for p in c.ports},
            quantities=self.quantity_decls(c.quantities, file, f"component {c.name}"),
            budgets=self.build_budgets(c.budgets, file),
            envelope=self.envelope(c.envelope, [], file),
            contains=sorted(
                (G.Contain(cd.ref.text, cd.count) for cd in c.contains), key=lambda x: x.ref
            ),
            doc=c.doc,
            src=f"{file}:{c.span.line}",
        )
        self._check_dup_ports(c, file)
        self.doc.nodes[name] = comp

    def _check_dup_ports(self, c: A.ComponentDecl | A.BindingDecl, file: str) -> None:
        seen: dict[str, Span] = {}
        for p in c.ports:
            if p.name in seen:
                self.bag.error("UEL0106", f"port '{p.name}' declared twice", p.span,
                               related=[("first declared here", seen[p.name])])
            seen[p.name] = p.span

    def build_budgets(self, decls: list[A.BudgetDecl], file: str) -> dict[str, G.Budget]:
        out: dict[str, G.Budget] = {}
        for b in decls:
            if b.name in out:
                self.bag.error("UEL0106", f"budget '{b.name}' declared twice", b.span)
                continue
            q = self.quantity(b.expr, file)
            if q is None: continue
            expected = _BUDGET_DIMS.get(b.name)
            if expected is not None and q.unit is not None:
                try:
                    d = parse_unit(q.unit).dim
                    if d != expected:
                        self.bag.error(
                            "UEL0307",
                            f"budget '{b.name}' expects {dim_name(expected)}, got '{q.unit}' ({dim_name(d)})",
                            b.span,
                            reason="named budgets participate in typed rollups: mass sums, unit_cost sums at qty, lead_time is max-over-path",
                        )
                except UnitError:
                    pass
            out[b.name] = G.Budget(b.op, q, b.at_qty)
        return out

    def build_requirement(self, r: A.RequirementDecl, ns: str, file: str) -> None:
        name = self.qualify(r, ns)
        self.doc.nodes[name] = G.Requirement(
            name, r.text, self.quantity_decls(r.quantities, file, f"requirement {r.name}"),
            r.doc, f"{file}:{r.span.line}",
        )

    def build_domain(self, d: A.DomainDecl, ns: str, file: str) -> None:
        name = self.qualify(d, ns)
        eff_unit = self.unit_of(d.effort_unit, d.span) if d.effort_unit else ""
        flo_unit = self.unit_of(d.flow_unit, d.span) if d.flow_unit else ""
        dom = G.DomainDef(
            name, d.dclass,
            G.EffortFlow(d.effort_name, eff_unit),
            G.EffortFlow(d.flow_name, flo_unit),
            d.doc, f"{file}:{d.span.line}",
        )
        if d.dclass == "power":
            if not (d.effort_name and d.flow_name):
                self.bag.error("UEL0208", f"power domain '{d.name}' needs both effort and flow", d.span)
            elif eff_unit or flo_unit:
                try:
                    got = dim_mul(parse_unit(eff_unit).dim, parse_unit(flo_unit).dim)
                    if got != D_POWER:
                        self.bag.error(
                            "UEL0304",
                            f"domain '{d.name}': effort '{eff_unit}' × flow '{flo_unit}' has dimension {dim_name(got)}, not power",
                            d.span,
                            reason="the kernel invariant: every power port's effort×flow product is power (spec §2.2)",
                        )
                except UnitError:
                    pass
        self.doc.nodes[name] = dom

    def build_process(self, p: A.ProcessDecl, ns: str, file: str) -> None:
        name = self.qualify(p, ns)
        rules: dict[str, G.DfmRule] = {}
        for r in p.rules:
            if r.name in rules:
                self.bag.error("UEL0106", f"rule '{r.name}' declared twice", r.span)
                continue
            limit = self.quantity(r.limit, file) if r.limit is not None else None
            rules[r.name] = G.DfmRule(r.feature, r.op, limit, r.message)
        self.doc.nodes[name] = G.ProcessDef(name, rules, p.doc, f"{file}:{p.span.line}")

    def build_binding(self, b: A.BindingDecl, ns: str, file: str) -> None:
        name = self.qualify(b, ns)
        self._check_member_collisions(name, b.ports, b.quantities, [])
        self.member_spans[("realizes", name)] = b.source.span
        if b.process:
            self.member_spans[("process", name)] = b.process.span
        if b.material:
            self.member_spans[("material", name)] = b.material.span
        if b.geometry_ref:
            self.member_spans[("geometry", name)] = b.geometry_ref.span
        for p in b.ports:
            self.member_spans[("port", name, p.name)] = p.domain.span
        quantities = self.quantity_decls(b.quantities, file, f"binding {b.target}")
        geom_name = ""
        if b.geometry_code:
            geom_name = f"{name}_geom"
            self.doc.nodes[geom_name] = G.Analysis(
                name=geom_name,
                akind="geometry",
                framing=G.Framing(model="geometry.code"),
                params=dict(quantities),
                core=G.Core("python", b.geometry_code),
                outputs={
                    "mass": G.OutputDecl("g", unc=True),
                    "volume": G.OutputDecl("mm^3"),
                },
                doc=f"generated by binding sugar from {b.target}",
                src=f"{file}:{b.span.line}",
            )
        elif b.geometry_ref is not None:
            geom_name = b.geometry_ref.text
        comp = G.Component(
            name=name,
            level="physical",
            ports={p.name: self.build_port(p, file, name) for p in b.ports},
            quantities=quantities,
            envelope=self.envelope(b.envelope, [], file),
            realizes=b.source.text,
            process=b.process.text if b.process else "",
            material=b.material.text if b.material else "",
            geometry=geom_name,
            datasheet=G.Datasheet(b.datasheet.source, b.datasheet.sha256) if b.datasheet else None,
            doc=b.doc,
            src=f"{file}:{b.span.line}",
        )
        self._check_dup_ports(b, file)
        self.doc.nodes[name] = comp

    def build_analysis(self, a: A.AnalysisDecl, ns: str, file: str) -> None:
        name = self.qualify(a, ns)
        if a.intent:
            self.member_spans[("intent", name)] = a.intent.ref.span
        for k in a.knowns:
            self.member_spans[("known", name, k.name)] = k.ref.span
        framing = G.Framing()
        if a.framing:
            framing.model = a.framing.model.text if a.framing.model else ""
            framing.envelope = self.envelope(a.framing.envelope, a.framing.claims, file)
        knowns: dict[str, str] = {}
        for k in a.knowns:
            if k.name in knowns:
                self.bag.error("UEL0106", f"known '{k.name}' declared twice", k.span)
                continue
            knowns[k.name] = k.ref.text
        outputs: dict[str, G.OutputDecl] = {}
        for o in a.outputs:
            if o.name in outputs:
                self.bag.error("UEL0106", f"output '{o.name}' declared twice", o.span)
                continue
            od = G.OutputDecl(self.unit_of(o.unit, o.unit_span), o.unc, o.artifact)
            if o.target_op and o.target_expr is not None:
                od.target_op = o.target_op
                self.member_spans[("target", name, o.name)] = o.target_expr.span \
                    if isinstance(o.target_expr, A.DottedRef) else o.span
                if isinstance(o.target_expr, A.DottedRef):
                    od.target_ref = o.target_expr.text  # canonicalized in pass C
                else:
                    od.target_value = self.quantity(o.target_expr, file)
                    self._check_target_type(name, o.name, od, od.target_value.unit if od.target_value else "",
                                            o.span)
            outputs[o.name] = od
        judgment = G.Judgment()
        if a.judgment:
            judgment = G.Judgment(a.judgment.status, a.judgment.text, a.judgment.doubts)
        intent = G.Intent()
        if a.intent:
            intent = G.Intent(a.intent.ref.text, a.intent.text)
        core = G.Core(a.core_lang or "python", a.core_path)
        if a.core_lang in ("expr", "stub"):
            core = G.Core(a.core_lang, "", X.canonical_body(a.core_body))
            self.res.expr_programs[name] = a.core_body
            if a.akind == "geometry":
                self.bag.error(
                    "UEL0310",
                    f"geometry '{a.name}' cannot use a {a.core_lang} core",
                    a.span,
                    reason="geometry cores must return topological assertions (spec §6.2); "
                           "expression bodies have no way to assert shape",
                )
        for t in a.core_tools:
            if t.name in core.tools:
                self.bag.error("UEL0106", f"tool '{t.name}' pinned twice", t.span)
                continue
            core.tools[t.name] = t.version
        if a.core_interface_path:
            core.interface = G.Datasheet(a.core_interface_path, a.core_interface_sha)
        verifies: list[G.Verify] = []
        for i, v in enumerate(a.verifies):
            gv = G.Verify(v.kind, v.output, v.ref.text if v.ref else "", v.known,
                          v.direction, v.path, v.tol, self.unit_of(v.tol_unit, v.tol_unit_span))
            if v.ref is not None:
                self.member_spans[("verify", name, i)] = v.ref.span
            self._check_verify(name, a, gv, v)
            verifies.append(gv)
        self.doc.nodes[name] = G.Analysis(
            name=name,
            akind=a.akind,
            intent=intent,
            framing=framing,
            knowns=knowns,
            params=self.quantity_decls(a.params, file, f"{a.akind} {a.name}"),
            core=core,
            outputs=outputs,
            verifies=verifies,
            judgment=judgment,
            doc=a.doc,
            src=f"{file}:{a.span.line}",
        )

    def _check_verify(self, name: str, a: A.AnalysisDecl, gv: G.Verify, v: A.VerifyDecl) -> None:
        outputs = {o.name: o for o in a.outputs}
        if gv.kind in ("against", "monotone"):
            if gv.output not in outputs:
                self.unresolved(gv.output, v.span, f"verify output on {name}", outputs)
                return
            if outputs[gv.output].artifact:
                self.bag.error("UEL0107", f"verify on '{name}.{gv.output}': artifact outputs "
                               "have no comparable value", v.span)
                return
        if gv.kind == "monotone":
            input_pool = {k.name for k in a.knowns} | {p.name for p in a.params}
            if gv.known not in input_pool:
                self.unresolved(gv.known, v.span, f"verify input on {name}", input_pool)
        if gv.tol_unit and gv.kind in ("against",):
            # absolute tolerance must be the same quantity type as the output
            try:
                tt = parse_unit(gv.tol_unit).vtype
                ot = parse_unit(outputs[gv.output].unit).vtype
                if tt != ot:
                    self.bag.error(
                        "UEL0302",
                        f"verify tolerance for '{name}.{gv.output}' is {type_name(*tt)}, "
                        f"but the output is {type_name(*ot)}",
                        v.tol_unit_span,
                    )
            except UnitError:
                pass
        if gv.kind == "case":
            p = self.project.root / gv.path
            if not p.is_file():
                self.bag.warning("UEL0809", f"{name}: golden case file '{gv.path}' does not exist yet",
                                 v.span,
                                 reason="the case runs at build time; a missing file will fail the run")

    def _check_target_type(self, node: str, out_name: str, od: G.OutputDecl,
                           target_unit: str, span: Span) -> None:
        """A target bound must be the same quantity type as the output it bounds."""
        try:
            ot = parse_unit(od.unit).vtype
            tt = parse_unit(target_unit).vtype
        except UnitError:
            return
        if ot != tt:
            self.bag.error(
                "UEL0302",
                f"target for '{node}.{out_name}' is {type_name(*tt)}, but the output is "
                f"declared '{od.unit or 'dimensionless'}' ({type_name(*ot)})",
                span,
            )

    # ------------------------------------------------------------------
    # cross-references

    def node_span(self, name: str) -> Span:
        return self.decl_spans.get(name, Span())

    def _suggest(self, name: str, pool) -> str | None:
        close = get_close_matches(name, list(pool), 1, 0.6)
        return close[0] if close else None

    def unresolved(self, ref: str, span: Span, what: str, pool=None) -> None:
        fix = None
        if pool:
            s = self._suggest(ref, pool)
            if s:
                fix = Fix(hint=f"did you mean '{s}'?", replace=s, span=span)
        self.bag.error("UEL0202", f"unresolved {what} '{ref}'", span, fix=fix)

    def lookup_node(self, ref: str) -> G.Node | None:
        return self.doc.nodes.get(ref)

    def lookup_domain(self, ref: str) -> G.DomainDef | None:
        for cand in (ref, f"lib.domains.{ref}"):
            n = self.doc.nodes.get(cand)
            if isinstance(n, G.DomainDef): return n
        return None

    def lookup_prefixed(self, ref: str, prefix: str, klass) -> G.Node | None:
        for cand in (ref, f"{prefix}.{ref}"):
            n = self.doc.nodes.get(cand)
            if isinstance(n, klass): return n
        return None

    def resolve_all_refs(self) -> None:
        for name, node in list(self.doc.nodes.items()):
            sp = self.node_span(name)
            if isinstance(node, G.Component):
                self.resolve_component_refs(name, node, sp)
            elif isinstance(node, G.Analysis):
                self.resolve_analysis_refs(name, node, sp)
        for idx, conn in enumerate(self.doc.connections):
            self.resolve_port_ref(conn.from_ref, self.mspan("connfrom", idx))
            self.resolve_port_ref(conn.to_ref, self.mspan("connto", idx))

    def resolve_port_ref(self, ref: str, span: Span) -> tuple[G.Component, str] | None:
        parts = ref.split(".")
        if len(parts) != 2:
            self.bag.error(
                "UEL0204",
                f"connection endpoint '{ref}' must be 'component.port'",
                span,
            )
            return None
        comp = self.doc.nodes.get(parts[0])
        if not isinstance(comp, G.Component):
            self.unresolved(parts[0], span, "component in connection",
                           (n for n, v in self.doc.nodes.items() if isinstance(v, G.Component)))
            return None
        if parts[1] not in comp.ports:
            fix = None
            s = self._suggest(parts[1], comp.ports)
            if s:
                fix = Fix(hint=f"did you mean '{parts[0]}.{s}'?", replace=f"{parts[0]}.{s}", span=span)
            self.bag.error("UEL0204", f"component '{parts[0]}' has no port '{parts[1]}'", span, fix=fix,
                           related=[("component defined here", self.node_span(parts[0]))])
            return None
        return comp, parts[1]

    def resolve_component_refs(self, name: str, comp: G.Component, sp: Span) -> None:
        if comp.realizes:
            rsp = self.mspan("realizes", name, default=sp)
            target = self.doc.nodes.get(comp.realizes)
            if not isinstance(target, G.Component):
                self.unresolved(comp.realizes, rsp, "binding source component",
                               (n for n, v in self.doc.nodes.items() if isinstance(v, G.Component)))
            elif target.level == "physical":
                self.bag.error(
                    "UEL0207",
                    f"'{name}' realizes '{comp.realizes}', which is already physical",
                    rsp,
                    reason="a binding is a refinement edge from a higher abstraction level to a lower one (spec §2.3)",
                )
        if comp.process:
            psp = self.mspan("process", name, default=sp)
            proc = self.lookup_prefixed(comp.process, "lib.process", G.ProcessDef)
            if proc is None:
                self.unresolved(comp.process, psp, "process",
                               [n.removeprefix("lib.process.") for n, v in self.doc.nodes.items()
                                if isinstance(v, G.ProcessDef)])
            else:
                comp.process = proc.name
        if comp.material:
            msp = self.mspan("material", name, default=sp)
            mat = self.lookup_prefixed(comp.material, "lib.materials", G.MaterialDef)
            if mat is None:
                self.unresolved(comp.material, msp, "material",
                               (n for n, v in self.doc.nodes.items() if isinstance(v, G.MaterialDef)))
            else:
                comp.material = mat.name
        if comp.geometry:
            g = self.doc.nodes.get(comp.geometry)
            if not isinstance(g, G.Analysis) or g.akind != "geometry":
                self.bag.error("UEL0203", f"'{comp.geometry}' is not a geometry node",
                               self.mspan("geometry", name, default=sp))
        for c in comp.contains:
            csp = self.mspan("contains", name, c.ref, default=sp)
            t = self.doc.nodes.get(c.ref)
            if t is None:
                self.unresolved(c.ref, csp, "contained component",
                               (n for n, v in self.doc.nodes.items() if isinstance(v, G.Component)))
            elif not isinstance(t, G.Component):
                self.bag.error("UEL0203", f"'{c.ref}' is contained by '{name}' but is not a component", csp)
        for pname, port in comp.ports.items():
            dsp = self.mspan("port", name, pname, default=sp)
            dom = self.lookup_domain(port.domain)
            if dom is None:
                self.unresolved(
                    port.domain, dsp, f"port domain (port '{pname}')",
                    [n.removeprefix("lib.domains.") for n, v in self.doc.nodes.items()
                     if isinstance(v, G.DomainDef)],
                )
                continue
            port.domain = dom.name.removeprefix("lib.domains.")
            self.check_port_attrs(name, pname, port, dom, dsp)

    def check_port_attrs(self, cname: str, pname: str, port: G.Port, dom: G.DomainDef, sp: Span) -> None:
        pairs = []
        if dom.effort.name:
            pairs.append((dom.effort.name, dom.effort.unit))
        if dom.flow.name:
            pairs.append((dom.flow.name, dom.flow.unit))
        expected = dict(pairs)
        expected["power"] = "W"
        for aname, q in port.attrs.items():
            exp_unit = expected.get(aname)
            if exp_unit is None or not q.unit: continue
            try:
                got, want = parse_unit(q.unit), parse_unit(exp_unit)
            except UnitError:
                continue
            if got.dim != want.dim:
                self.bag.error(
                    "UEL0305",
                    f"port '{cname}.{pname}' ({port.domain}): attribute '{aname}' must be {dim_name(want.dim)}, got '{q.unit}' ({dim_name(got.dim)})",
                    sp,
                    reason=f"the '{port.domain}' domain defines {aname} in {exp_unit} (domain table, spec §2.2)",
                )

    def resolve_analysis_refs(self, name: str, an: G.Analysis, sp: Span) -> None:
        if an.intent.ref:
            if self.doc.nodes.get(an.intent.ref) is None:
                self.unresolved(an.intent.ref, self.mspan("intent", name, default=sp), "intent target",
                               (n for n in self.doc.nodes
                                if n.startswith("req.") or isinstance(self.doc.nodes[n], G.Analysis)))
        for local, ref in list(an.knowns.items()):
            ksp = self.mspan("known", name, local, default=sp)
            rr = self.resolve_value_ref(ref, ksp, f"known '{local}' of {name}")
            if rr is not None:
                an.knowns[local] = rr.target
                self.res.known_refs[(name, local)] = rr
        for out_name, od in an.outputs.items():
            if not od.target_ref: continue
            tsp = self.mspan("target", name, out_name, default=sp)
            rr = self.resolve_value_ref(od.target_ref, tsp, f"target of {name}.{out_name}")
            if rr is None: continue
            od.target_ref = rr.target
            self.res.target_refs[(name, out_name)] = rr
            self._check_target_type(name, out_name, od, rr.unit, tsp)
        for i, gv in enumerate(an.verifies):
            if gv.kind != "against" or not gv.ref: continue
            vsp = self.mspan("verify", name, i, default=sp)
            rr = self.resolve_value_ref(gv.ref, vsp, f"verify reference on {name}.{gv.output}")
            if rr is None: continue
            gv.ref = rr.target
            self.res.verify_refs[(name, i)] = rr
            out = an.outputs.get(gv.output)
            if out is not None:
                try:
                    ot = parse_unit(out.unit).vtype
                    rt = parse_unit(rr.unit).vtype
                    if ot != rt:
                        self.bag.error(
                            "UEL0302",
                            f"verify on '{name}.{gv.output}' ({type_name(*ot)}) cross-checks "
                            f"against '{rr.target}' ({type_name(*rt)}) — different quantity types",
                            vsp,
                        )
                except UnitError:
                    pass

    def resolve_value_ref(self, ref: str, span: Span, what: str) -> ResolvedRef | None:
        parts = ref.split(".")
        # req.NAME.quantity / lib.ns.NAME.quantity resolution by longest node prefix
        node_name = None
        for cut in range(len(parts), 0, -1):
            cand = ".".join(parts[:cut])
            if cand in self.doc.nodes:
                node_name = cand
                rest = parts[cut:]
                break
        if node_name is None:
            self.unresolved(ref, span, what, self.doc.nodes.keys())
            return None
        node = self.doc.nodes[node_name]
        if isinstance(node, (G.Requirement, G.MaterialDef)):
            if len(rest) != 1:
                self.bag.error("UEL0205", f"{what}: expected '{node_name}.<quantity>'", span)
                return None
            q = node.quantities.get(rest[0])
            if q is None:
                fix = None
                s = self._suggest(rest[0], node.quantities)
                if s:
                    fix = Fix(hint=f"did you mean '{node_name}.{s}'?", replace=f"{node_name}.{s}", span=span)
                self.bag.error("UEL0202", f"{what}: '{node_name}' has no quantity '{rest[0]}'", span,
                               fix=fix, related=[("defined here", self.node_span(node_name))])
                return None
            return ResolvedRef(f"{node_name}.{rest[0]}", node_name, q.unit, "quantity", q)
        if isinstance(node, G.Analysis):
            if len(rest) == 2 and rest[0] == "outputs":
                out = node.outputs.get(rest[1])
                if out is None:
                    fix = None
                    s = self._suggest(rest[1], node.outputs)
                    if s:
                        fix = Fix(hint=f"did you mean '{node_name}.outputs.{s}'?",
                                  replace=f"{node_name}.outputs.{s}", span=span)
                    self.bag.error("UEL0202", f"{what}: '{node_name}' has no output '{rest[1]}'",
                                   span, fix=fix)
                    return None
                return ResolvedRef(f"{node_name}.outputs.{rest[1]}", node_name, out.unit, "output")
            if len(rest) == 1 and rest[0] in node.outputs:
                self.bag.error(
                    "UEL0205",
                    f"{what}: analysis outputs are addressed through '.outputs.'",
                    span,
                    fix=Fix(hint=f"write '{node_name}.outputs.{rest[0]}'",
                            replace=f"{node_name}.outputs.{rest[0]}", span=span),
                )
                return None
            self.bag.error("UEL0205", f"{what}: expected '{node_name}.outputs.<name>'", span)
            return None
        if isinstance(node, G.Component):
            if len(rest) == 1:
                q = node.quantities.get(rest[0])
                if q is not None:
                    return ResolvedRef(f"{node_name}.{rest[0]}", node_name, q.unit, "quantity", q)
                # geometry-output fallthrough (spec §5.2: spar_v7.section_props)
                if node.geometry:
                    g = self.doc.nodes.get(node.geometry)
                    if isinstance(g, G.Analysis) and rest[0] in g.outputs:
                        return ResolvedRef(
                            f"{node.geometry}.outputs.{rest[0]}", node.geometry,
                            g.outputs[rest[0]].unit, "output",
                        )
                pool = list(node.quantities) + list(node.ports)
                if node.geometry and isinstance(self.doc.nodes.get(node.geometry), G.Analysis):
                    pool += list(self.doc.nodes[node.geometry].outputs)  # type: ignore[union-attr]
                fix = None
                s = self._suggest(rest[0], pool)
                if s:
                    fix = Fix(hint=f"did you mean '{node_name}.{s}'?", replace=f"{node_name}.{s}", span=span)
                self.bag.error("UEL0202", f"{what}: '{node_name}' has no quantity '{rest[0]}'", span,
                               fix=fix, related=[("defined here", self.node_span(node_name))])
                return None
            if len(rest) == 2:
                port = node.ports.get(rest[0])
                if port is None:
                    fix = None
                    s = self._suggest(rest[0], node.ports)
                    if s:
                        fix = Fix(hint=f"did you mean '{node_name}.{s}'?",
                                  replace=f"{node_name}.{s}.{rest[1]}", span=span)
                    self.bag.error("UEL0202", f"{what}: '{node_name}' has no port '{rest[0]}'", span, fix=fix)
                    return None
                q = port.attrs.get(rest[1])
                if q is None:
                    fix = None
                    s = self._suggest(rest[1], port.attrs)
                    if s:
                        fix = Fix(hint=f"did you mean '{node_name}.{rest[0]}.{s}'?",
                                  replace=f"{node_name}.{rest[0]}.{s}", span=span)
                    self.bag.error("UEL0202", f"{what}: port '{node_name}.{rest[0]}' has no attribute '{rest[1]}'",
                                   span, fix=fix)
                    return None
                return ResolvedRef(ref, node_name, q.unit, "port_attr", q)
            self.bag.error("UEL0205", f"{what}: too many path segments in '{ref}'", span)
            return None
        self.bag.error("UEL0203", f"{what}: '{node_name}' ({node.KIND}) does not provide values", span)
        return None

    # ------------------------------------------------------------------
    # expr/stub core type checking (v0.2, ADR-0005)

    def check_expr_programs(self) -> None:
        """Dimensional inference over every expr/stub core body: the formula
        itself is under the units checker, before anything runs."""
        for name, stmts in sorted(self.res.expr_programs.items()):
            an = self.doc.nodes.get(name)
            if not isinstance(an, G.Analysis): continue
            env: dict[str, X.VType] = {}
            for local in an.knowns:
                rr = self.res.known_refs.get((name, local))
                if rr is None:
                    continue  # unresolved reference already diagnosed
                try:
                    env[local] = parse_unit(rr.unit).vtype
                except UnitError:
                    env[local] = (parse_unit("").dim, False)
            for pname, q in an.params.items():
                try:
                    env[pname] = parse_unit(q.unit).vtype
                except UnitError:
                    continue
            outputs = {oname: od.unit for oname, od in an.outputs.items() if not od.artifact}
            for oname, od in an.outputs.items():
                if od.artifact:
                    self.bag.error(
                        "UEL0310",
                        f"{name}: artifact output '{oname}' is not producible by a "
                        f"{an.core.lang} core",
                        self.node_span(name),
                        reason="artifacts (meshes, fields) come from python cores; expressions produce quantities",
                    )
            X.infer_program(name, stmts, env, outputs, self.bag,
                            self.node_span(name), stub=an.core.lang == "stub")

    # ------------------------------------------------------------------
    # cycles

    def check_cycles(self) -> None:
        # containment
        edges: dict[str, list[str]] = {}
        for name, node in self.doc.nodes.items():
            if isinstance(node, G.Component):
                edges[name] = [c.ref for c in node.contains if c.ref in self.doc.nodes]
        cyc = _find_cycle(edges)
        if cyc:
            self.bag.error(
                "UEL0206", "containment cycle: " + " -> ".join(cyc),
                self.node_span(cyc[0]),
                reason="a component cannot transitively contain itself; mass and cost rollups would diverge",
            )
        # knowns (analysis dependency) at node granularity
        dedges: dict[str, list[str]] = {}
        for (consumer, _), rr in self.res.known_refs.items():
            dedges.setdefault(consumer, []).append(rr.node)
        cyc = _find_cycle(dedges)
        if cyc:
            self.bag.error(
                "UEL0206", "reference cycle through knowns: " + " -> ".join(cyc),
                self.node_span(cyc[0]),
                reason="an analysis cannot (transitively) consume its own outputs; staleness could never settle",
            )

def _find_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    stack: list[str] = []

    def dfs(u: str) -> list[str] | None:
        color[u] = GRAY
        stack.append(u)
        for v in edges.get(u, ()):
            st = color.get(v, WHITE)
            if st == GRAY:
                i = stack.index(v)
                return stack[i:] + [v]
            if st == WHITE:
                r = dfs(v)
                if r: return r
        stack.pop()
        color[u] = BLACK
        return None

    for u in list(edges):
        if color.get(u, WHITE) == WHITE:
            r = dfs(u)
            if r: return r
    return None

def resolve_project(project: Project, bag: Bag) -> Resolution:
    return Resolver(project, bag).run()
