"""Recursive-descent parser: tokens → surface AST (uel.uast).

Error philosophy (program §4, Phase 2): agents iterate against errors. Every parse
diagnostic states what was expected, and — where the fix is mechanical — carries a
`fix` the agent can apply verbatim. On an item-level error the parser records the
diagnostic and resynchronizes at the next top-level keyword, so one mistake yields
one message, not a cascade.
"""

from __future__ import annotations

from difflib import get_close_matches
from typing import Optional

from .diagnostics import Bag, Fix, Span
from .lexer import Comment, T, Token, lex
from .units import is_unit_symbol
from . import expr as E
from . import uast as A

TOP_KEYWORDS = (
    "requirement", "component", "binding", "analysis", "geometry", "connect",
    "domain", "claim", "material", "process", "model",
)

_SEPS = (T.NEWLINE, T.SEMI, T.COMMA)

class Parser:
    def __init__(self, text: str, file: str, bag: Bag):
        self.file = file
        self.bag = bag
        self.toks, self.comments = lex(text, file, bag)
        self.i = 0

    # -- token plumbing ----------------------------------------------------

    def cur(self) -> Token:
        return self.toks[self.i]

    def peek(self, k: int = 1) -> Token:
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j]

    def at(self, kind: T) -> bool:
        return self.cur().kind == kind

    def at_ident(self, *vals: str) -> bool:
        return self.cur().kind == T.IDENT and self.cur().text in vals

    def bump(self) -> Token:
        t = self.cur()
        if t.kind != T.EOF:
            self.i += 1
        return t

    def eat(self, kind: T) -> Optional[Token]:
        if self.at(kind): return self.bump()
        return None

    def eat_ident(self, val: str) -> Optional[Token]:
        if self.at_ident(val): return self.bump()
        return None

    def span(self, t: Token) -> Span:
        return t.span(self.file)

    def err(self, msg: str, t: Token | None = None, **kw) -> None:
        t = t or self.cur()
        code = "UEL0104" if t.kind == T.EOF else "UEL0101"
        self.bag.error(code, msg, self.span(t), **kw)

    def expect(self, kind: T, what: str, **kw) -> Optional[Token]:
        if self.at(kind): return self.bump()
        self.err(f"expected {what}, found {self.describe(self.cur())}", **kw)
        return None

    def expect_ident_val(self, val: str, context: str) -> Optional[Token]:
        if self.at_ident(val): return self.bump()
        self.err(f"expected '{val}' {context}, found {self.describe(self.cur())}")
        return None

    @staticmethod
    def describe(t: Token) -> str:
        if t.kind == T.EOF: return "end of file"
        if t.kind == T.NEWLINE: return "end of line"
        if t.kind in (T.IDENT, T.NUMBER): return f"'{t.text}'"
        if t.kind == T.STRING: return "string literal"
        return f"'{t.text}'"

    def skip_seps(self) -> None:
        while self.cur().kind in _SEPS:
            self.bump()

    def skip_newlines(self) -> None:
        while self.at(T.NEWLINE):
            self.bump()

    def ident(self, what: str) -> Optional[str]:
        t = self.expect(T.IDENT, what)
        return t.text if t else None

    def string(self, what: str) -> str:
        t = self.expect(T.STRING, what)
        return t.text if t else ""

    def recover_to_item(self) -> None:
        depth = 0
        while not self.at(T.EOF):
            t = self.cur()
            if t.kind == T.LBRACE:
                depth += 1
            elif t.kind == T.RBRACE:
                if depth == 0:
                    self.bump()
                    return
                depth -= 1
            elif depth == 0 and t.kind == T.IDENT and t.text in TOP_KEYWORDS: return
            self.bump()

    # -- dotted names ------------------------------------------------------

    def dotted(self, what: str) -> Optional[A.DottedRef]:
        first = self.expect(T.IDENT, what)
        if not first: return None
        parts = [first.text]
        end = first
        while self.at(T.DOT):
            self.bump()
            nxt = self.expect(T.IDENT, f"name after '.' in {what}")
            if not nxt: break
            parts.append(nxt.text)
            end = nxt
        sp = Span(self.file, first.line, first.col, end.col + len(end.text))
        return A.DottedRef(parts, sp)

    # -- numbers, units, quantities ---------------------------------------

    def signed_number(self, what: str) -> Optional[float]:
        neg = False
        if self.at(T.MINUS):
            self.bump()
            neg = True
        t = self.expect(T.NUMBER, what)
        if not t: return None
        v = t.value if t.value is not None else 0.0
        return -v if neg else v

    def _at_unit_start(self) -> bool:
        if self.at(T.LPAREN): return True
        if not self.at(T.IDENT): return False
        # contextual words that end a value context rather than start a unit
        return self.cur().text not in ("in", "because", "from", "qty", "doubts", "x")

    def unit_tokens(self) -> tuple[str, Span]:
        """Collect a unit expression: IDENT/(…) (^ int)? ((*|/) …)*, textually."""
        parts: list[str] = []
        first = self.cur()
        last = first

        def factor() -> bool:
            nonlocal last
            if self.at(T.LPAREN):
                parts.append("(")
                self.bump()
                if not expr(): return False
                if not self.at(T.RPAREN):
                    self.err("expected ')' in unit expression")
                    return False
                parts.append(")")
                last = self.bump()
            elif self.at(T.IDENT):
                last = self.bump()
                parts.append(last.text)
            else:
                self.err("expected unit symbol")
                return False
            if self.at(T.CARET):
                self.bump()
                parts.append("^")
                neg = ""
                if self.at(T.MINUS):
                    self.bump()
                    neg = "-"
                t = self.expect(T.NUMBER, "integer exponent after '^'")
                if not t: return False
                parts.append(neg + t.text)
                last = t
            return True

        def expr() -> bool:
            if not factor(): return False
            while self.at(T.STAR) or self.at(T.SLASH):
                parts.append(self.bump().text)
                if not factor(): return False
            return True

        ok = expr()
        text = "".join(parts) if ok else ""
        sp = Span(self.file, first.line, first.col, last.col + len(last.text))
        return text, sp

    def maybe_unit(self) -> tuple[str, Span]:
        if self._at_unit_start(): return self.unit_tokens()
        return "", self.span(self.cur())

    def unc_tail(self, allow_bare: bool = False) -> Optional[A.UncTail]:
        if not self.at(T.PM): return None
        pm = self.bump()
        sp = self.span(pm)
        if self.at_ident("cal"):
            self.bump()
            return A.UncTail("cal", span=sp)
        if self.at(T.NUMBER) or self.at(T.MINUS):
            v = self.signed_number("uncertainty value")
            if v is None: return A.UncTail("abs", 0.0, span=sp)
            if self.at(T.PERCENT):
                self.bump()
                return A.UncTail("rel", v / 100.0, span=sp)
            unit, _ = self.maybe_unit()
            return A.UncTail("abs", v, unit, span=sp)
        if allow_bare: return A.UncTail("bare", span=sp)
        self.err("expected uncertainty after '±': a value ('± 10 g'), a percentage ('± 5 %'), or 'cal'",
                 reason="uncertainty is first-class; a bare '±' is only meaningful on output declarations")
        return A.UncTail("cal", span=sp)

    def qexpr(self, what: str, allow_ref: bool = True) -> Optional[A.QExpr]:
        t = self.cur()
        if t.kind == T.LBRACKET: return self.interval()
        if t.kind == T.NUMBER or t.kind == T.MINUS:
            start = self.cur()
            v = self.signed_number(what)
            if v is None: return None
            unit, usp = self.maybe_unit()
            unc = self.unc_tail()
            return A.QNumber(v, unit, usp, unc, self.span(start))
        if t.kind == T.IDENT and allow_ref: return self.dotted(what)
        self.err(f"expected {what} (a number, interval '[lo, hi]', or reference), found {self.describe(t)}")
        return None

    def interval(self) -> Optional[A.QInterval]:
        lb = self.expect(T.LBRACKET, "'['")
        if not lb: return None
        lo = self.signed_number("interval lower bound")
        if lo is None: return None
        self.eat(T.COMMA)
        hi = self.signed_number("interval upper bound")
        if hi is None: return None
        unit, usp, inside = "", self.span(self.cur()), True
        if self._at_unit_start():
            unit, usp = self.unit_tokens()
        rb = self.expect(T.RBRACKET, "']' to close interval",
                         fix=Fix(hint="close the interval with ']'", replace="]"))
        if unit == "" and self._at_unit_start():
            unit, usp = self.unit_tokens()
            inside = False
        unc = self.unc_tail()
        sp = self.span(lb)
        if lo > hi:
            self.bag.error("UEL0306", f"interval lower bound {lo:g} exceeds upper bound {hi:g}", sp,
                           fix=Fix(hint=f"write the interval as [{hi:g}, {lo:g}]"))
        _ = rb
        return A.QInterval(lo, hi, unit, usp, unc, sp, inside)

    def quantity_decl(self, name_tok: Token, eq_expected: str = "=") -> Optional[A.QuantityDecl]:
        """`name = qexpr [from "detail"]` (components/requirements/materials/params)."""
        if eq_expected == "=" and self.at(T.COLON):
            self.bag.error(
                "UEL0107",
                f"quantity '{name_tok.text}' is declared with ':' but quantities use '='",
                self.span(self.cur()),
                reason="':' declares typed slots (ports, outputs); '=' assigns quantity values",
                fix=Fix(hint="replace ':' with '='", replace="=", span=self.span(self.cur())),
            )
            self.bump()
        elif not self.expect(T.EQ, f"'=' after quantity name '{name_tok.text}'"): return None
        expr = self.qexpr(f"value for '{name_tok.text}'")
        if expr is None: return None
        prov = ""
        if self.eat_ident("from"):
            prov = self.string("provenance detail string after 'from'")
        return A.QuantityDecl(name_tok.text, expr, prov, self.span(name_tok))

    # -- expressions (v0.2, core expr/stub bodies) -------------------------

    _BINOPS = {T.PLUS: ("+", 10), T.MINUS: ("-", 10),
               T.STAR: ("*", 20), T.SLASH: ("/", 20), T.CARET: ("^", 40)}

    def expression(self, min_prec: int = 0) -> Optional[E.Expr]:
        """Pratt parser. A statement's expression ends at newline, but a line
        may continue after a binary operator or inside parentheses."""
        lhs = self.expr_unary()
        if lhs is None: return None
        while True:
            info = self._BINOPS.get(self.cur().kind)
            if info is None or info[1] < min_prec: return lhs
            op, prec = info
            op_tok = self.bump()
            self.skip_newlines()  # trailing-operator continuation
            rhs = self.expression(prec if op == "^" else prec + 1)  # ^ is right-assoc
            if rhs is None: return None
            lhs = E.EBin(op, lhs, rhs, self.span(op_tok))

    def expr_unary(self) -> Optional[E.Expr]:
        if self.at(T.MINUS):
            mt = self.bump()
            x = self.expression(31)  # binds looser than ^, tighter than * /
            if x is None: return None
            return E.EUn("-", x, self.span(mt))
        return self.expr_primary()

    def expr_primary(self) -> Optional[E.Expr]:
        t = self.cur()
        if t.kind == T.NUMBER:
            nt = self.bump()
            unit, usp = self.expr_unit_scan()
            return E.ENum(nt.value if nt.value is not None else 0.0, unit, usp, self.span(nt))
        if t.kind == T.LPAREN:
            self.bump()
            self.skip_newlines()
            ex = self.expression(0)
            self.skip_newlines()
            self.expect(T.RPAREN, "')' to close the expression group")
            return ex
        if t.kind == T.IDENT:
            if self.peek().kind == T.LPAREN: return self.expr_call()
            ref = self.dotted("name in expression")
            if ref is None: return None
            return E.ERef(ref.text, ref.span)
        self.err(f"expected an expression, found {self.describe(t)}",
                 reason="expressions are built from numbers (with units), names, "
                        "functions, and + - * / ^")
        return None

    def expr_call(self) -> Optional[E.Expr]:
        fn = self.bump()
        self.bump()  # '('
        args: list[E.Expr] = []
        self.skip_newlines()
        if not self.at(T.RPAREN):
            while True:
                a = self.expression(0)
                if a is None: return None
                args.append(a)
                self.skip_newlines()
                if self.at(T.COMMA):
                    self.bump()
                    self.skip_newlines()
                    continue
                break
        self.expect(T.RPAREN, f"')' to close the arguments of {fn.text}()")
        return E.ECall(fn.text, args, self.span(fn))

    def expr_unit_scan(self) -> tuple[str, Span]:
        """A unit after a numeric literal, consumed greedily but *validated*:
        an identifier chain is a unit only while each symbol resolves in the
        unit table, so `3 m / span` divides (3 m) by the name `span`."""
        usp = self.span(self.cur())
        if not (self.at(T.IDENT) and is_unit_symbol(self.cur().text)): return "", usp
        parts: list[str] = []

        def one_symbol() -> None:
            parts.append(self.bump().text)
            if self.at(T.CARET) and (
                self.peek().kind == T.NUMBER
                or (self.peek().kind == T.MINUS and self.peek(2).kind == T.NUMBER)
            ):
                self.bump()
                parts.append("^")
                if self.at(T.MINUS):
                    self.bump()
                    parts.append("-")
                parts.append(self.bump().text)

        one_symbol()
        while self.cur().kind in (T.STAR, T.SLASH) and \
                self.peek().kind == T.IDENT and is_unit_symbol(self.peek().text):
            parts.append(self.bump().text)
            one_symbol()
        return "".join(parts), usp

    def expr_block(self, kind: str) -> list[E.ExprStmt]:
        """The body of `core expr { … }` / `core stub { … }`."""
        stmts: list[E.ExprStmt] = []
        if not self.expect(T.LBRACE, f"'{{' after 'core {kind}'"): return stmts
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            is_let = False
            if self.at_ident("let"):
                self.bump()
                is_let = True
            nt = self.expect(T.IDENT, "assignment target (an output name, or 'let name')")
            if nt is None: break
            if not self.expect(T.EQ, f"'=' after '{nt.text}'"): break
            ex = self.expression(0)
            if ex is None: break
            unc = self.unc_tail() if kind == "stub" and not is_let else None
            stmts.append(E.ExprStmt(nt.text, is_let, ex, unc, self.span(nt)))
            self.skip_seps()
        self.expect(T.RBRACE, f"'}}' to close core {kind}")
        return stmts

    # -- envelope ----------------------------------------------------------

    def envelope_block(self) -> A.EnvelopeBlock:
        kw = self.bump()  # 'envelope'
        blk = A.EnvelopeBlock(span=self.span(kw))
        if not self.expect(T.LBRACE, "'{' after 'envelope'"): return blk
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            if self.at_ident("assume", "require"):
                blk.items.append(self.env_claim())
            elif self.at(T.IDENT):
                p = self.env_predicate()
                if p:
                    blk.items.append(p)
                else:
                    break
            else:
                self.err("expected an envelope item: 'var in [lo, hi]', 'var <= bound', 'assume claim', or 'require claim'")
                break
            self.skip_seps()
        self.expect(T.RBRACE, "'}' to close envelope")
        return blk

    def env_claim(self) -> A.EnvClaim:
        kw = self.bump()
        name = self.ident(f"claim name after '{kw.text}'") or "?"
        rationale = ""
        if self.eat_ident("because"):
            rationale = self.string("rationale string after 'because'")
        return A.EnvClaim(kw.text, name, rationale, self.span(kw))

    def env_predicate(self) -> Optional[A.EnvPredicate]:
        var_tok = self.bump()
        var = var_tok.text
        if self.at_ident("in"):
            self.bump()
            iv = self.interval()
            if iv is None: return None
            return A.EnvPredicate(var, iv.lo, iv.hi, iv.unit, iv.unit_span, True, span=self.span(var_tok))
        if self.cur().kind in (T.LE, T.GE, T.LT, T.GT):
            op_tok = self.bump()
            v = self.signed_number(f"bound for '{var}'")
            if v is None: return None
            unit, usp = self.maybe_unit()
            lo, hi = (None, v) if op_tok.kind in (T.LE, T.LT) else (v, None)
            return A.EnvPredicate(var, lo, hi, unit, usp, False, op_tok.text, self.span(var_tok))
        self.err(
            f"expected 'in [lo, hi]' or a bound ('<=', '>=') after envelope variable '{var}'",
            reason="value predicates fence where a model is valid (spec §2.5)",
        )
        return None

    # -- ports -------------------------------------------------------------

    def port_decl(self) -> Optional[A.PortDecl]:
        kw = self.bump()  # 'port'
        name = self.ident("port name")
        if name is None: return None
        if not self.expect(T.COLON, f"':' after port name '{name}' (ports are typed by domain)"):
            return None
        domain = self.dotted("port domain (e.g. electrical, mechanical.translation)")
        if domain is None: return None
        port = A.PortDecl(name, domain, span=self.span(kw))
        if self.eat(T.LBRACE):
            self.skip_seps()
            while not self.at(T.RBRACE) and not self.at(T.EOF):
                if self.at_ident("direction"):
                    self.bump()
                    d = self.ident("'in', 'out', or 'inout' after 'direction'")
                    if d and d not in ("in", "out", "inout"):
                        self.bag.error("UEL0107", f"direction must be in/out/inout, got '{d}'",
                                       self.span(self.toks[self.i - 1]))
                        d = ""
                    port.dir = d or ""
                elif self.at_ident("protocol"):
                    self.bump()
                    port.protocol = self.string("protocol name string")
                elif self.at_ident("doc"):
                    self.bump()
                    port.doc = self.string("doc string")
                elif self.at(T.IDENT):
                    attr_tok = self.bump()
                    if not self.expect(T.COLON, f"':' after port attribute '{attr_tok.text}'"):
                        break
                    expr = self.qexpr(f"value for port attribute '{attr_tok.text}'")
                    if expr is None: break
                    prov = ""
                    if self.eat_ident("from"):
                        prov = self.string("provenance detail string after 'from'")
                    port.attrs.append(A.PortAttr(attr_tok.text, expr, prov, self.span(attr_tok)))
                else:
                    self.err("expected a port attribute ('name: value'), 'direction', 'protocol', or 'doc'")
                    break
                self.skip_seps()
            self.expect(T.RBRACE, "'}' to close port block")
        return port

    # -- components --------------------------------------------------------

    def component_decl(self) -> Optional[A.ComponentDecl]:
        kw = self.bump()
        name = self.ident("component name")
        if name is None: return None
        level = "functional"
        if self.eat(T.COLON):
            lt = self.ident("abstraction level: functional, behavioral, or physical")
            if lt in ("functional", "behavioral", "physical"):
                level = lt
            elif lt is not None:
                close = get_close_matches(lt, ["functional", "behavioral", "physical"], 1, 0.5)
                self.bag.error(
                    "UEL0107", f"unknown abstraction level '{lt}'",
                    self.span(self.toks[self.i - 1]),
                    reason="every component exists at a declared abstraction level (spec §2.3)",
                    fix=Fix(hint=f"use one of functional/behavioral/physical"
                                 + (f"; did you mean '{close[0]}'?" if close else ""),
                            replace=close[0] if close else None,
                            span=self.span(self.toks[self.i - 1])),
                )
        comp = A.ComponentDecl(name, level, span=self.span(kw))
        if not self.expect(T.LBRACE, f"'{{' to open component '{name}'"): return comp
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            if self.at_ident("port"):
                p = self.port_decl()
                if p:
                    comp.ports.append(p)
            elif self.at_ident("budget"):
                b = self.budget_decl()
                if b:
                    comp.budgets.append(b)
            elif self.at_ident("envelope"):
                comp.envelope = self.envelope_block()
            elif self.at_ident("contains"):
                c = self.contains_decl()
                if c:
                    comp.contains.append(c)
            elif self.at_ident("doc"):
                self.bump()
                comp.doc = self.string("doc string")
            elif self.at(T.IDENT):
                nt = self.bump()
                q = self.quantity_decl(nt)
                if q:
                    comp.quantities.append(q)
                else:
                    break
            else:
                self.err("expected a component item: port, budget, envelope, contains, doc, or 'name = value'")
                break
            self.skip_seps()
        self.expect(T.RBRACE, f"'}}' to close component '{name}'")
        return comp

    def budget_decl(self) -> Optional[A.BudgetDecl]:
        kw = self.bump()
        name = self.ident("budget name (e.g. mass, unit_cost, lead_time)")
        if name is None: return None
        if self.at(T.LE) or self.at(T.GE):
            op = self.bump().text
        else:
            self.err(f"expected '<=' or '>=' after budget '{name}'",
                     reason="budgets are one-sided limits; rollups compute the margin")
            return None
        expr = self.qexpr(f"limit for budget '{name}'", allow_ref=False)
        if expr is None: return None
        at_qty = None
        if self.eat(T.AT):
            self.expect_ident_val("qty", "after '@' in a cost budget")
            t = self.expect(T.NUMBER, "quantity break (an integer) after '@ qty'")
            if t and t.value is not None:
                at_qty = int(t.value)
        return A.BudgetDecl(name, op, expr, at_qty, self.span(kw))

    def contains_decl(self) -> Optional[A.ContainsDecl]:
        kw = self.bump()
        ref = self.dotted("contained component name")
        if ref is None: return None
        count = 1
        if self.at_ident("x"):
            self.bump()
            t = self.expect(T.NUMBER, "count after 'x'")
            if t and t.value is not None:
                count = int(t.value)
                if count < 1 or t.value != count:
                    self.bag.error("UEL0107", f"contains count must be a positive integer, got '{t.text}'",
                                   self.span(t))
                    count = 1
        return A.ContainsDecl(ref, count, self.span(kw))

    # -- bindings ----------------------------------------------------------

    def binding_decl(self) -> Optional[A.BindingDecl]:
        kw = self.bump()
        source = self.dotted("functional component to bind")
        if source is None: return None
        if not self.expect(T.ARROW_R, "'->' between the functional identity and its realization"):
            return None
        target = self.ident("realization name")
        if target is None: return None
        if self.eat(T.COLON):
            lv = self.ident("'physical' after ':'")
            if lv != "physical":
                self.bag.error("UEL0107", f"bindings produce physical realizations; got '{lv}'",
                               self.span(self.toks[self.i - 1]),
                               fix=Fix(hint="write ': physical'", replace="physical",
                                       span=self.span(self.toks[self.i - 1])))
        b = A.BindingDecl(source, target, span=self.span(kw))
        if not self.expect(T.LBRACE, f"'{{' to open binding '{target}'"): return b
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            if self.at_ident("process"):
                self.bump()
                b.process = self.dotted("process name (e.g. cnc_3axis)")
            elif self.at_ident("material"):
                self.bump()
                mat = self.dotted("material name")
                if mat and self.eat_ident("from"):
                    libpath = self.dotted("library path after 'from'")
                    if libpath:
                        mat = A.DottedRef(libpath.parts + mat.parts, mat.span)
                b.material = mat
            elif self.at_ident("geometry"):
                self.bump()
                if self.at_ident("code"):
                    self.bump()
                    b.geometry_code = self.string("path string to the geometry script")
                else:
                    b.geometry_ref = self.dotted("geometry node reference (or 'code \"path\"')")
            elif self.at_ident("datasheet"):
                dt = self.bump()
                srcp = self.string("datasheet source path/URI string")
                ds = A.DatasheetRef(srcp, span=self.span(dt))
                if self.eat_ident("sha256"):
                    ds.sha256 = self.string("sha256 hex string")
                b.datasheet = ds
            elif self.at_ident("port"):
                p = self.port_decl()
                if p:
                    b.ports.append(p)
            elif self.at_ident("envelope"):
                b.envelope = self.envelope_block()
            elif self.at_ident("doc"):
                self.bump()
                b.doc = self.string("doc string")
            elif self.at(T.IDENT):
                nt = self.bump()
                q = self.quantity_decl(nt)
                if q:
                    b.quantities.append(q)
                else:
                    break
            else:
                self.err("expected a binding item: process, material, geometry code, datasheet, port, envelope, doc, or 'name = value'")
                break
            self.skip_seps()
        self.expect(T.RBRACE, f"'}}' to close binding '{target}'")
        return b

    # -- analyses ----------------------------------------------------------

    def analysis_decl(self, akind: str) -> Optional[A.AnalysisDecl]:
        kw = self.bump()
        name = self.ident(f"{akind} name")
        if name is None: return None
        an = A.AnalysisDecl(name, akind, span=self.span(kw))
        if not self.expect(T.LBRACE, f"'{{' to open {akind} '{name}'"): return an
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            if self.at_ident("intent"):
                it = self.bump()
                ref = self.dotted("intent target (the requirement or decision this analysis serves)")
                if ref is None: break
                text = self.cur().text if self.at(T.STRING) else ""
                if self.at(T.STRING):
                    self.bump()
                an.intent = A.IntentDecl(ref, text, self.span(it))
            elif self.at_ident("framing"):
                an.framing = self.framing_block()
            elif self.at_ident("knowns"):
                self.bump()
                if self.expect(T.LBRACE, "'{' after 'knowns'"):
                    self.skip_seps()
                    while self.at(T.IDENT):
                        nt = self.bump()
                        if not self.expect(T.ARROW_L, f"'<-' after known '{nt.text}' (knowns are references into the graph, never copies)"):
                            break
                        ref = self.dotted(f"reference for known '{nt.text}'")
                        if ref is None: break
                        an.knowns.append(A.KnownDecl(nt.text, ref, self.span(nt)))
                        self.skip_seps()
                    self.expect(T.RBRACE, "'}' to close knowns")
            elif self.at_ident("params"):
                self.bump()
                if self.expect(T.LBRACE, "'{' after 'params'"):
                    self.skip_seps()
                    while self.at(T.IDENT):
                        nt = self.bump()
                        q = self.quantity_decl(nt)
                        if q is None: break
                        an.params.append(q)
                        self.skip_seps()
                    self.expect(T.RBRACE, "'}' to close params")
            elif self.at_ident("core"):
                self.bump()
                lang = self.ident("core language: python, expr, or stub") or ""
                an.core_lang = lang
                if lang in ("expr", "stub"):
                    an.core_body = self.expr_block(lang)
                else:
                    an.core_path = self.string("path string to the core script")
                    if self.at(T.LBRACE):
                        self.core_meta_block(an)
            elif self.at_ident("verify"):
                v = self.verify_decl()
                if v is not None:
                    an.verifies.append(v)
            elif self.at_ident("outputs"):
                self.bump()
                if self.expect(T.LBRACE, "'{' after 'outputs'"):
                    self.skip_seps()
                    while self.at(T.IDENT):
                        o = self.output_decl()
                        if o is None: break
                        an.outputs.append(o)
                        self.skip_seps()
                    self.expect(T.RBRACE, "'}' to close outputs")
            elif self.at_ident("judgment"):
                jt = self.bump()
                status = self.ident("judgment status: pending, accepted, rejected, or superseded") or "pending"
                if status not in ("pending", "accepted", "rejected", "superseded"):
                    close = get_close_matches(status, ["pending", "accepted", "rejected", "superseded"], 1, 0.5)
                    self.bag.error("UEL0107", f"unknown judgment status '{status}'",
                                   self.span(self.toks[self.i - 1]),
                                   fix=Fix(hint="use pending/accepted/rejected/superseded",
                                           replace=close[0] if close else None,
                                           span=self.span(self.toks[self.i - 1])))
                    status = "pending"
                j = A.JudgmentDecl(status, span=self.span(jt))
                if self.at(T.STRING):
                    j.text = self.bump().text
                if self.eat_ident("doubts"):
                    j.doubts = self.string("doubts string")
                an.judgment = j
            elif self.at_ident("doc"):
                self.bump()
                an.doc = self.string("doc string")
            else:
                self.err(
                    "expected an analysis item: intent, framing, knowns, params, core, verify, outputs, judgment, or doc"
                )
                break
            self.skip_seps()
        self.expect(T.RBRACE, f"'}}' to close {akind} '{name}'")
        return an

    def core_meta_block(self, an: A.AnalysisDecl) -> None:
        """v0.3 (ADR-0008): `core python "path" { tool "name" "ver"  interface "file" sha256 "…" }`
        — what wraps the black box is declarable, hashed, and packed for review."""
        self.bump()  # '{'
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            if self.at_ident("tool"):
                tt = self.bump()
                tname = self.string("tool name string (e.g. \"su2\")")
                tver = self.string("tool version string (pin it — versions are identity)")
                an.core_tools.append(A.CoreToolDecl(tname, tver, self.span(tt)))
            elif self.at_ident("interface"):
                self.bump()
                an.core_interface_path = self.string("interface manifest path (e.g. an FMU modelDescription.xml)")
                if self.eat_ident("sha256"):
                    an.core_interface_sha = self.string("sha256 hex string")
            else:
                self.err("expected 'tool \"name\" \"version\"' or 'interface \"path\" [sha256 \"…\"]' in core block")
                break
            self.skip_seps()
        self.expect(T.RBRACE, "'}' to close the core block")

    def verify_decl(self) -> Optional[A.VerifyDecl]:
        """`verify <out> against <ref> within <tol>` | `verify <out> monotone with
        <input> rising|falling` | `verify case "file" within <tol>` (ADR-0008)."""
        kw = self.bump()
        if self.at_ident("case"):
            self.bump()
            path = self.string("golden case file path (JSON with inputs + expect)")
            if not self.expect_ident_val("within", "after the case file"): return None
            tol, unit, usp = self.tol_tail()
            if tol is None: return None
            return A.VerifyDecl("case", path=path, tol=tol, tol_unit=unit,
                                tol_unit_span=usp, span=self.span(kw))
        if self.at_ident("converged"):
            self.bump()
            metric = self.ident("convergence metric name the core reports (e.g. residual)")
            if metric is None: return None
            if not self.expect(T.LE, f"'<=' after 'verify converged {metric}'"): return None
            thr = self.signed_number("convergence threshold")
            if thr is None: return None
            if thr < 0:
                self.bag.error("UEL0107", f"convergence threshold must be >= 0, got {thr:g}",
                               self.span(self.toks[self.i - 1]))
                return None
            return A.VerifyDecl("converged", output=metric, tol=thr, span=self.span(kw))
        out = self.ident("output name to verify (or 'case'/'converged')")
        if out is None: return None
        if self.at_ident("against"):
            self.bump()
            ref = self.dotted("value reference to cross-check against")
            if ref is None: return None
            if not self.expect_ident_val("within", "after the cross-check reference"): return None
            tol, unit, usp = self.tol_tail()
            if tol is None: return None
            return A.VerifyDecl("against", output=out, ref=ref, tol=tol, tol_unit=unit,
                                tol_unit_span=usp, span=self.span(kw))
        if self.at_ident("monotone"):
            self.bump()
            if not self.expect_ident_val("with", "after 'monotone'"): return None
            known = self.ident("input name to perturb")
            if known is None: return None
            d = self.ident("'rising' or 'falling'")
            if d not in ("rising", "falling"):
                self.bag.error("UEL0107", f"monotone direction must be rising or falling, got '{d}'",
                               self.span(self.toks[self.i - 1]))
                return None
            return A.VerifyDecl("monotone", output=out, known=known, direction=d, span=self.span(kw))
        self.err(f"expected 'against', 'monotone', 'case', or 'converged' after 'verify {out}'",
                 reason="verification contracts are machine-checkable reasons to believe an opaque core (ADR-0008)")
        return None

    def tol_tail(self) -> tuple[Optional[float], str, Span]:
        """`within 10 %` (relative, stored as fraction) or `within 0.5 dB` (absolute)."""
        usp = self.span(self.cur())
        v = self.signed_number("tolerance after 'within'")
        if v is None: return None, "", usp
        if v <= 0:
            self.bag.error("UEL0107", f"verification tolerance must be positive, got {v:g}",
                           self.span(self.toks[self.i - 1]))
            return None, "", usp
        if self.at(T.PERCENT):
            self.bump()
            return v / 100.0, "", usp
        unit, usp = self.unit_tokens()
        return v, unit, usp

    def framing_block(self) -> A.FramingDecl:
        kw = self.bump()
        fr = A.FramingDecl(span=self.span(kw))
        if not self.expect(T.LBRACE, "'{' after 'framing'"): return fr
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            if self.at_ident("model"):
                self.bump()
                fr.model = self.dotted("physics model name (e.g. beam.euler_bernoulli)")
            elif self.at_ident("assume", "require"):
                fr.claims.append(self.env_claim())
            elif self.at_ident("covers"):
                ct = self.bump()
                names = self.ident_list("hazard name after 'covers'")
                fr.covers.extend(A.EnvClaim("covers", n, span=self.span(ct)) for n in names)
            elif self.at_ident("waive"):
                wt = self.bump()
                nm = self.ident("hazard name after 'waive'") or "?"
                if self.eat_ident("because"):
                    reason = self.string("waiver rationale string after 'because'")
                    fr.waives.append(A.EnvClaim("waive", nm, reason, self.span(wt)))
                else:
                    self.err(f"expected 'because \"reason\"' after 'waive {nm}'",
                             reason="a waiver without a reason is denial; say why this "
                                    "hazard does not apply here (v0.6)")
                    break
            elif self.at_ident("envelope"):
                fr.envelope = self.envelope_block()
            else:
                self.err("expected a framing item: model, assume, require, covers, waive, or envelope")
                break
            self.skip_seps()
        self.expect(T.RBRACE, "'}' to close framing")
        return fr

    def ident_list(self, what: str) -> list[str]:
        names: list[str] = []
        n0 = self.ident(what)
        if n0:
            names.append(n0)
        while self.at(T.COMMA):
            self.bump()
            nn = self.ident(f"{what.split(' after ')[0]} in list")
            if nn is None: break
            names.append(nn)
        return names

    def output_decl(self) -> Optional[A.OutputDeclA]:
        nt = self.bump()
        if not self.expect(T.COLON, f"':' after output name '{nt.text}'"): return None
        out = A.OutputDeclA(nt.text, span=self.span(nt))
        if self.at_ident("artifact"):
            self.bump()
            out.artifact = True
        elif self.at_ident("dimensionless"):
            t = self.bump()
            out.unit_span = self.span(t)
        elif self._at_unit_start():
            out.unit, out.unit_span = self.unit_tokens()
        else:
            self.err(f"expected a unit, 'dimensionless', or 'artifact' for output '{nt.text}'",
                     reason="outputs are typed, unit-carrying quantities (spec §3.2)")
            return None
        unc = self.unc_tail(allow_bare=True)
        if unc is not None:
            out.unc = True
        if self.at_ident("target"):
            self.bump()
            if self.at(T.GE) or self.at(T.LE):
                out.target_op = self.bump().text
            else:
                self.err(f"expected '>=' or '<=' after 'target' on output '{nt.text}'",
                         reason="a target is the one-sided acceptance bound this output must satisfy (v0.2)")
                return out
            te = self.qexpr(f"target bound for output '{nt.text}'")
            if te is None: return out
            if isinstance(te, A.QInterval) or (isinstance(te, A.QNumber) and te.unc is not None):
                self.bag.error("UEL0107",
                               f"target for '{nt.text}' must be a plain bound (a number with unit, or a reference)",
                               self.span(self.toks[self.i - 1]),
                               reason="the acceptance line has no uncertainty of its own; bands live on values")
            else:
                out.target_expr = te
        return out

    # -- simple items ------------------------------------------------------

    def connect_decl(self) -> Optional[A.ConnectDecl]:
        kw = self.bump()
        a = self.dotted("connection source 'component.port'")
        if a is None: return None
        if not self.expect(T.ARROW_R, "'->' between connected ports"): return None
        b = self.dotted("connection target 'component.port'")
        if b is None: return None
        return A.ConnectDecl(a, b, self.span(kw))

    def requirement_decl(self) -> Optional[A.RequirementDecl]:
        kw = self.bump()
        name = self.ident("requirement name (e.g. STR-014)")
        if name is None: return None
        req = A.RequirementDecl(name, span=self.span(kw))
        if not self.expect(T.LBRACE, f"'{{' to open requirement '{name}'"): return req
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            if self.at_ident("text"):
                self.bump()
                req.text = self.string("requirement text string")
            elif self.at_ident("doc"):
                self.bump()
                req.doc = self.string("doc string")
            elif self.at(T.IDENT):
                nt = self.bump()
                q = self.quantity_decl(nt)
                if q is None: break
                req.quantities.append(q)
            else:
                self.err("expected 'text \"...\"' or 'name = value' in requirement")
                break
            self.skip_seps()
        self.expect(T.RBRACE, f"'}}' to close requirement '{name}'")
        return req

    def domain_decl(self) -> Optional[A.DomainDecl]:
        kw = self.bump()
        name_ref = self.dotted("domain name (may be dotted, e.g. mechanical.translation)")
        if name_ref is None: return None
        name = name_ref.text
        dom = A.DomainDecl(name, span=self.span(kw))
        if not self.expect(T.LBRACE, f"'{{' to open domain '{name}'"): return dom
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            if self.at_ident("class"):
                self.bump()
                c = self.ident("'power', 'material', or 'data' after 'class'")
                if c in ("power", "material", "data"):
                    dom.dclass = c
                elif c is not None:
                    self.bag.error("UEL0107", f"unknown domain class '{c}'",
                                   self.span(self.toks[self.i - 1]))
            elif self.at_ident("effort", "flow"):
                which = self.bump().text
                nm = self.ident(f"{which} attribute name") or ""
                self.expect(T.COLON, f"':' after {which} name")
                unit, _ = self.unit_tokens()
                if which == "effort":
                    dom.effort_name, dom.effort_unit = nm, unit
                else:
                    dom.flow_name, dom.flow_unit = nm, unit
            elif self.at_ident("doc"):
                self.bump()
                dom.doc = self.string("doc string")
            else:
                self.err("expected a domain item: class, effort, flow, or doc")
                break
            self.skip_seps()
        self.expect(T.RBRACE, f"'}}' to close domain '{name}'")
        return dom

    def claim_decl(self) -> Optional[A.ClaimDecl]:
        kw = self.bump()
        name = self.ident("claim name")
        if name is None: return None
        cl = A.ClaimDecl(name, span=self.span(kw))
        if not self.expect(T.LBRACE, f"'{{' to open claim '{name}'"): return cl
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            if self.at_ident("entails", "excludes"):
                which = self.bump().text
                names = self.ident_list(f"claim name after '{which}'")
                if which == "entails":
                    cl.entails.extend(names)
                else:
                    cl.excludes.extend(names)
            elif self.at_ident("doc"):
                self.bump()
                cl.doc = self.string("doc string")
            else:
                self.err("expected 'entails', 'excludes', or 'doc' in claim")
                break
            self.skip_seps()
        self.expect(T.RBRACE, f"'}}' to close claim '{name}'")
        return cl

    def material_decl(self) -> Optional[A.MaterialDecl]:
        kw = self.bump()
        name = self.ident("material name")
        if name is None: return None
        mat = A.MaterialDecl(name, span=self.span(kw))
        if not self.expect(T.LBRACE, f"'{{' to open material '{name}'"): return mat
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            if self.at_ident("doc"):
                self.bump()
                mat.doc = self.string("doc string")
            elif self.at(T.IDENT):
                nt = self.bump()
                q = self.quantity_decl(nt)
                if q is None: break
                mat.quantities.append(q)
            else:
                self.err("expected 'name = value' property in material")
                break
            self.skip_seps()
        self.expect(T.RBRACE, f"'}}' to close material '{name}'")
        return mat

    def process_decl(self) -> Optional[A.ProcessDecl]:
        kw = self.bump()
        name = self.ident("process name")
        if name is None: return None
        proc = A.ProcessDecl(name, span=self.span(kw))
        if not self.expect(T.LBRACE, f"'{{' to open process '{name}'"): return proc
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            if self.at_ident("rule"):
                r = self.rule_decl()
                if r:
                    proc.rules.append(r)
                else:
                    break
            elif self.at_ident("doc"):
                self.bump()
                proc.doc = self.string("doc string")
            else:
                self.err("expected 'rule name: feature <op> limit \"why\"' in process")
                break
            self.skip_seps()
        self.expect(T.RBRACE, f"'}}' to close process '{name}'")
        return proc

    def rule_decl(self) -> Optional[A.RuleDecl]:
        kw = self.bump()
        name = self.ident("rule name")
        if name is None: return None
        if not self.expect(T.COLON, f"':' after rule name '{name}'"): return None
        if self.at_ident("forbid", "require"):
            op = self.bump().text
            feature = self.ident(f"feature name after '{op}'") or "?"
            msg = self._rule_message()
            return A.RuleDecl(name, feature, op, None, msg, self.span(kw))
        feature = self.ident("feature name (a geometry-declared feature quantity)")
        if feature is None: return None
        if self.at(T.GE) or self.at(T.LE):
            op = self.bump().text
        else:
            self.err(f"expected '>=', '<=' after feature '{feature}', or 'forbid'/'require' before it")
            return None
        limit = self.qexpr(f"limit for rule '{name}'", allow_ref=False)
        if limit is None: return None
        msg = self._rule_message()
        return A.RuleDecl(name, feature, op, limit, msg, self.span(kw))

    def model_decl(self) -> Optional[A.ModelDecl]:
        """v0.6: `model beam.euler_bernoulli { hazard ltb "why it kills" … }` —
        a registered physics model carries the failure modes it cannot see."""
        kw = self.bump()
        name_ref = self.dotted("model name (dotted, e.g. beam.euler_bernoulli)")
        if name_ref is None: return None
        md = A.ModelDecl(name_ref.text, span=self.span(kw))
        if not self.expect(T.LBRACE, f"'{{' to open model '{md.name}'"): return md
        self.skip_seps()
        while not self.at(T.RBRACE) and not self.at(T.EOF):
            if self.at_ident("hazard"):
                ht = self.bump()
                nm = self.ident("hazard name (a structural claim naming the failure mode)")
                if nm is None: break
                why = self.string(f"one-line reason string: why '{nm}' kills designs this model cannot warn about")
                md.hazards.append(A.EnvClaim("hazard", nm, why, self.span(ht)))
            elif self.at_ident("doc"):
                self.bump()
                md.doc = self.string("doc string")
            else:
                self.err("expected 'hazard name \"why\"' or 'doc' in model")
                break
            self.skip_seps()
        self.expect(T.RBRACE, f"'}}' to close model '{md.name}'")
        return md

    def _rule_message(self) -> str:
        """Rule rationale string; may sit on a continuation line."""
        j = self.i
        while self.toks[j].kind == T.NEWLINE:
            j += 1
        if self.toks[j].kind == T.STRING:
            self.i = j
            return self.bump().text
        return ""

    # -- file --------------------------------------------------------------

    def parse_file(self) -> A.ASTFile:
        ast = A.ASTFile(self.file, comments=self.comments)
        self.skip_seps()
        while not self.at(T.EOF):
            t = self.cur()
            if t.kind != T.IDENT:
                self.err(f"expected a top-level item ({', '.join(TOP_KEYWORDS)})")
                self.recover_to_item()
                self.skip_seps()
                continue
            word = t.text
            item: Optional[A.Item] = None
            before = self.i
            if word == "component":
                item = self.component_decl()
            elif word == "binding":
                item = self.binding_decl()
            elif word == "analysis":
                item = self.analysis_decl("analysis")
            elif word == "geometry":
                item = self.analysis_decl("geometry")
            elif word == "requirement":
                item = self.requirement_decl()
            elif word == "connect":
                item = self.connect_decl()
            elif word == "domain":
                item = self.domain_decl()
            elif word == "claim":
                item = self.claim_decl()
            elif word == "material":
                item = self.material_decl()
            elif word == "process":
                item = self.process_decl()
            elif word == "model":
                item = self.model_decl()
            else:
                close = get_close_matches(word, TOP_KEYWORDS, 1, 0.6)
                self.bag.error(
                    "UEL0105",
                    f"unknown top-level item '{word}'",
                    self.span(t),
                    fix=Fix(
                        hint=f"did you mean '{close[0]}'?" if close
                        else f"top-level items are: {', '.join(TOP_KEYWORDS)}",
                        replace=close[0] if close else None,
                        span=self.span(t),
                    ),
                )
                self.bump()
                self.recover_to_item()
            if item is not None:
                ast.items.append(item)
            if self.i == before:  # no progress: hard recovery
                self.bump()
                self.recover_to_item()
            self.skip_seps()
        return ast

def parse_text(text: str, file: str, bag: Bag) -> A.ASTFile:
    return Parser(text, file, bag).parse_file()
