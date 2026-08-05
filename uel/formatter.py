"""The one zero-config formatter (program §4, Phase 2).

Canonical layout, re-printed from the AST: two-space indent, one declaration per
line, one blank line between top-level items, `=` for quantities, `:` for typed
slots, interval units inside the bracket (`[0, 12 kN]`). Comments are preserved:
own-line comments re-attach before the next item at the appropriate indent;
trailing comments stay on their line.

Graded invariants (conformance kind `fmt`): idempotence (fmt∘fmt = fmt) and AST
preservation (fingerprint(parse(fmt(x))) == fingerprint(parse(x))).
"""

from __future__ import annotations

from . import expr as E
from . import uast as A
from .lexer import Comment


def _num(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


def _unc(u: A.UncTail | None) -> str:
    if u is None:
        return ""
    if u.kind == "cal":
        return " ± cal"
    if u.kind == "bare":
        return " ±"
    if u.kind == "rel":
        return f" ± {_num((u.value or 0.0) * 100)} %"
    unit = f" {u.unit}" if u.unit else ""
    return f" ± {_num(u.value or 0.0)}{unit}"


def _qexpr(e: A.QExpr) -> str:
    if isinstance(e, A.DottedRef):
        return e.text
    if isinstance(e, A.QNumber):
        unit = f" {e.unit}" if e.unit else ""
        return f"{_num(e.value)}{unit}{_unc(e.unc)}"
    unit_in = f" {e.unit}" if e.unit else ""
    return f"[{_num(e.lo)}, {_num(e.hi)}{unit_in}]{_unc(e.unc)}"


class Formatter:
    def __init__(self, ast: A.ASTFile):
        self.ast = ast
        self.lines: list[str] = []
        # own-line comments sorted by source line, consumed as items pass them
        self.pending = sorted(
            (c for c in ast.comments if c.own_line), key=lambda c: c.line
        )
        self.trailing = {c.line: c for c in ast.comments if not c.own_line}
        self.pi = 0

    def emit_comments_before(self, line: int, indent: int) -> None:
        while self.pi < len(self.pending) and self.pending[self.pi].line <= line:
            c = self.pending[self.pi]
            self.lines.append("  " * indent + f"# {c.text}" if c.text else "  " * indent + "#")
            self.pi += 1

    def put(self, indent: int, text: str, src_line: int = 0) -> None:
        if src_line:
            self.emit_comments_before(src_line, indent)
        line = "  " * indent + text
        if src_line and src_line in self.trailing:
            line += f"  # {self.trailing[src_line].text}"
        self.lines.append(line)

    # ------------------------------------------------------------------

    def format(self) -> str:
        first = True
        for item in self.ast.items:
            if not first:
                self.lines.append("")
            first = False
            self.item(item)
        # any comments after the last item
        self.emit_comments_before(10**9, 0)
        return "\n".join(self.lines).rstrip("\n") + "\n"

    def item(self, item: A.Item) -> None:
        if isinstance(item, A.ComponentDecl):
            self.component(item)
        elif isinstance(item, A.BindingDecl):
            self.binding(item)
        elif isinstance(item, A.AnalysisDecl):
            self.analysis(item)
        elif isinstance(item, A.RequirementDecl):
            self.requirement(item)
        elif isinstance(item, A.ConnectDecl):
            self.put(0, f"connect {item.from_ref.text} -> {item.to_ref.text}", item.span.line)
        elif isinstance(item, A.DomainDecl):
            self.domain(item)
        elif isinstance(item, A.ClaimDecl):
            self.claim(item)
        elif isinstance(item, A.MaterialDecl):
            self.material(item)
        elif isinstance(item, A.ProcessDecl):
            self.process(item)

    def _doc(self, doc: str, indent: int) -> None:
        if doc:
            self.put(indent, f'doc "{_esc(doc)}"')

    def component(self, c: A.ComponentDecl) -> None:
        self.put(0, f"component {c.name} : {c.level} {{", c.span.line)
        self._doc(c.doc, 1)
        for p in c.ports:
            self.port(p, 1)
        for q in c.quantities:
            self.quantity(q, 1)
        for b in c.budgets:
            at = f" @ qty {b.at_qty}" if b.at_qty is not None else ""
            self.put(1, f"budget {b.name} {b.op} {_qexpr(b.expr)}{at}", b.span.line)
        for ct in c.contains:
            cnt = f" x {ct.count}" if ct.count != 1 else ""
            self.put(1, f"contains {ct.ref.text}{cnt}", ct.span.line)
        if c.envelope:
            self.envelope(c.envelope, 1)
        self.put(0, "}")

    def quantity(self, q: A.QuantityDecl, indent: int) -> None:
        prov = f' from "{_esc(q.prov_detail)}"' if q.prov_detail else ""
        self.put(indent, f"{q.name} = {_qexpr(q.expr)}{prov}", q.span.line)

    def port(self, p: A.PortDecl, indent: int) -> None:
        head = f"port {p.name} : {p.domain.text}"
        if not (p.dir or p.protocol or p.attrs or p.doc):
            self.put(indent, head, p.span.line)
            return
        self.put(indent, head + " {", p.span.line)
        if p.doc:
            self._doc(p.doc, indent + 1)
        if p.dir:
            self.put(indent + 1, f"direction {p.dir}")
        if p.protocol:
            self.put(indent + 1, f'protocol "{_esc(p.protocol)}"')
        for a in p.attrs:
            prov = f' from "{_esc(a.prov_detail)}"' if a.prov_detail else ""
            self.put(indent + 1, f"{a.name}: {_qexpr(a.expr)}{prov}", a.span.line)
        self.put(indent, "}")

    def envelope(self, env: A.EnvelopeBlock, indent: int) -> None:
        self.put(indent, "envelope {", env.span.line)
        for it in env.items:
            if isinstance(it, A.EnvPredicate):
                self.put(indent + 1, self.pred_text(it), it.span.line)
            else:
                because = f' because "{_esc(it.rationale)}"' if it.rationale else ""
                self.put(indent + 1, f"{it.keyword} {it.claim}{because}", it.span.line)
        self.put(indent, "}")

    @staticmethod
    def pred_text(p: A.EnvPredicate) -> str:
        if p.interval_form or (p.lo is not None and p.hi is not None):
            unit = f" {p.unit}" if p.unit else ""
            return f"{p.var} in [{_num(p.lo or 0)}, {_num(p.hi or 0)}{unit}]"
        unit = f" {p.unit}" if p.unit else ""
        if p.hi is not None:
            return f"{p.var} <= {_num(p.hi)}{unit}"
        return f"{p.var} >= {_num(p.lo or 0)}{unit}"

    def binding(self, b: A.BindingDecl) -> None:
        self.put(0, f"binding {b.source.text} -> {b.target} : physical {{", b.span.line)
        self._doc(b.doc, 1)
        if b.process:
            self.put(1, f"process {b.process.text}")
        if b.material:
            self.put(1, f"material {b.material.text}")
        if b.geometry_code:
            self.put(1, f'geometry code "{_esc(b.geometry_code)}"')
        elif b.geometry_ref:
            self.put(1, f"geometry {b.geometry_ref.text}")
        if b.datasheet:
            sha = f' sha256 "{b.datasheet.sha256}"' if b.datasheet.sha256 else ""
            self.put(1, f'datasheet "{_esc(b.datasheet.source)}"{sha}', b.datasheet.span.line)
        for p in b.ports:
            self.port(p, 1)
        for q in b.quantities:
            self.quantity(q, 1)
        if b.envelope:
            self.envelope(b.envelope, 1)
        self.put(0, "}")

    def analysis(self, a: A.AnalysisDecl) -> None:
        self.put(0, f"{a.akind} {a.name} {{", a.span.line)
        self._doc(a.doc, 1)
        if a.intent:
            text = f' "{_esc(a.intent.text)}"' if a.intent.text else ""
            self.put(1, f"intent {a.intent.ref.text}{text}", a.intent.span.line)
        if a.framing:
            self.put(1, "framing {", a.framing.span.line)
            if a.framing.model:
                self.put(2, f"model {a.framing.model.text}")
            for cl in a.framing.claims:
                because = f' because "{_esc(cl.rationale)}"' if cl.rationale else ""
                self.put(2, f"{cl.keyword} {cl.claim}{because}", cl.span.line)
            if a.framing.envelope:
                self.envelope(a.framing.envelope, 2)
            self.put(1, "}")
        if a.knowns:
            self.put(1, "knowns {")
            for k in a.knowns:
                self.put(2, f"{k.name} <- {k.ref.text}", k.span.line)
            self.put(1, "}")
        if a.params:
            self.put(1, "params {")
            for q in a.params:
                self.quantity(q, 2)
            self.put(1, "}")
        if a.core_lang in ("expr", "stub"):
            self.put(1, f"core {a.core_lang} {{")
            for st in a.core_body:
                self.put(2, E.format_stmt(st), st.span.line)
            self.put(1, "}")
        elif a.core_path:
            head = f'core {a.core_lang or "python"} "{_esc(a.core_path)}"'
            if a.core_tools or a.core_interface_path:
                self.put(1, head + " {")
                for t in a.core_tools:
                    self.put(2, f'tool "{_esc(t.name)}" "{_esc(t.version)}"', t.span.line)
                if a.core_interface_path:
                    sha = f' sha256 "{a.core_interface_sha}"' if a.core_interface_sha else ""
                    self.put(2, f'interface "{_esc(a.core_interface_path)}"{sha}')
                self.put(1, "}")
            else:
                self.put(1, head)
        for v in a.verifies:
            self.put(1, _verify_text(v), v.span.line)
        if a.outputs:
            self.put(1, "outputs {")
            for o in a.outputs:
                if o.artifact:
                    ty = "artifact"
                elif o.unit:
                    ty = o.unit
                else:
                    ty = "dimensionless"
                pm = " ±" if o.unc else ""
                tgt = ""
                if o.target_op and o.target_expr is not None:
                    tgt = f" target {o.target_op} {_qexpr(o.target_expr)}"
                self.put(2, f"{o.name} : {ty}{pm}{tgt}", o.span.line)
            self.put(1, "}")
        if a.judgment:
            j = a.judgment
            parts = [f"judgment {j.status}"]
            if j.text:
                parts.append(f'"{_esc(j.text)}"')
            if j.doubts:
                parts.append(f'doubts "{_esc(j.doubts)}"')
            self.put(1, " ".join(parts), j.span.line)
        self.put(0, "}")

    def requirement(self, r: A.RequirementDecl) -> None:
        self.put(0, f"requirement {r.name} {{", r.span.line)
        self._doc(r.doc, 1)
        if r.text:
            self.put(1, f'text "{_esc(r.text)}"')
        for q in r.quantities:
            self.quantity(q, 1)
        self.put(0, "}")

    def domain(self, d: A.DomainDecl) -> None:
        self.put(0, f"domain {d.name} {{", d.span.line)
        self.put(1, f"class {d.dclass}")
        if d.effort_name:
            self.put(1, f"effort {d.effort_name}: {d.effort_unit}")
        if d.flow_name:
            self.put(1, f"flow {d.flow_name}: {d.flow_unit}")
        self._doc(d.doc, 1)
        self.put(0, "}")

    def claim(self, c: A.ClaimDecl) -> None:
        body = bool(c.doc or c.entails or c.excludes)
        if not body:
            self.put(0, f"claim {c.name} {{ }}", c.span.line)
            return
        self.put(0, f"claim {c.name} {{", c.span.line)
        self._doc(c.doc, 1)
        if c.entails:
            self.put(1, "entails " + ", ".join(c.entails))
        if c.excludes:
            self.put(1, "excludes " + ", ".join(c.excludes))
        self.put(0, "}")

    def material(self, m: A.MaterialDecl) -> None:
        self.put(0, f"material {m.name} {{", m.span.line)
        self._doc(m.doc, 1)
        for q in m.quantities:
            self.quantity(q, 1)
        self.put(0, "}")

    def process(self, p: A.ProcessDecl) -> None:
        self.put(0, f"process {p.name} {{", p.span.line)
        self._doc(p.doc, 1)
        for r in p.rules:
            if r.op in ("forbid", "require"):
                head = f"rule {r.name}: {r.op} {r.feature}"
            else:
                head = f"rule {r.name}: {r.feature} {r.op} {_qexpr(r.limit)}" if r.limit else f"rule {r.name}: {r.feature} {r.op}"
            self.put(1, head, r.span.line)
            if r.message:
                self.put(2, f'"{_esc(r.message)}"')
        self.put(0, "}")


def _verify_text(v: A.VerifyDecl) -> str:
    tol = ""
    if v.tol is not None:
        tol = f" within {_num(v.tol * 100)} %" if not v.tol_unit else f" within {_num(v.tol)} {v.tol_unit}"
    if v.kind == "case":
        return f'verify case "{_esc(v.path)}"{tol}'
    if v.kind == "against":
        return f"verify {v.output} against {v.ref.text if v.ref else '?'}{tol}"
    return f"verify {v.output} monotone with {v.known} {v.direction}"


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def format_ast(ast: A.ASTFile) -> str:
    return Formatter(ast).format()
