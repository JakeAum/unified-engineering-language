"""The declarative expression layer (v0.2, ADR-0005): `core expr` bodies.

v0.1's honest limit was that the physics lived inside opaque Python cores — the
kernel typed the shell (units, references, fences, staleness) and trusted the
formula. Most cores were under thirty lines of arithmetic over their knowns.
This module puts that arithmetic *in the language*, which buys three things:

1. **Dimensional inference at compile time.** Every expression's type —
   dimension plus level flag (uel.units, ADR-0006) — is inferred from the types
   of the knowns it consumes, before anything runs. A link budget that forgets
   to convert a data rate into a level is a compile error naming both types,
   not a wrong margin.

2. **Computed uncertainty.** Evaluation is interval arithmetic over
   (lo, nominal, hi) triples seeded from the knowns' declared bands. The output
   band is a guaranteed enclosure — worst-case, not statistical. A core that
   wants RSS-style 1σ bookkeeping stays a Python core; the two coexist.

3. **Content-addressed formulas.** The canonical formatted body is the core's
   identity (`Core.text`); a whitespace re-flow is not a change, an edited
   coefficient invalidates exactly its cone.

Level arithmetic follows the one rule (ADR-0006): levels add where linear
quantities multiply — `Level(D1) + Level(D2) = Level(D1·D2)`, subtraction
divides, `dB` is `Level(1)`. `db()`/`lin()` cross between the scales. The
evaluator itself is type-blind: after inference has proven legality, level
math *is* plain arithmetic on the canonical dB numbers.

Grammar (parsed by uel.parser, printed here):

    stmt  := ['let'] NAME '=' expr
    expr  := standard precedence: ^ (right) over unary - over * / over + -
    atom  := NUMBER [unit] | dotted-ref | fn '(' expr {',' expr} ')' | '(' expr ')'

A unit after a numeric literal is consumed greedily but *validated*: an
identifier chain is taken as a unit only while each symbol resolves in the unit
table, so `3 m / span` is (3 m) ÷ span. Statements end at newline; a line may
continue after a binary operator or inside parentheses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Optional, Union

from .diagnostics import Bag, Span
from .units import (
    DIMENSIONLESS,
    Dim,
    UnitError,
    dim_div,
    dim_mul,
    dim_pow,
    parse_unit,
    type_name,
    _d,
)

# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------


@dataclass
class ENum:
    value: float
    unit: str = ""
    unit_span: Span = field(default_factory=Span)
    span: Span = field(default_factory=Span)


@dataclass
class ERef:
    name: str  # possibly dotted: a known, param, let, output, or const.*
    span: Span = field(default_factory=Span)


@dataclass
class EUn:
    op: str  # "-"
    x: "Expr" = None  # type: ignore[assignment]
    span: Span = field(default_factory=Span)


@dataclass
class EBin:
    op: str  # + - * / ^
    l: "Expr" = None  # type: ignore[assignment]
    r: "Expr" = None  # type: ignore[assignment]
    span: Span = field(default_factory=Span)


@dataclass
class ECall:
    fn: str
    args: list["Expr"] = field(default_factory=list)
    span: Span = field(default_factory=Span)


Expr = Union[ENum, ERef, EUn, EBin, ECall]


@dataclass
class ExprStmt:
    target: str
    is_let: bool
    expr: Expr = None  # type: ignore[assignment]
    span: Span = field(default_factory=Span)


# ---------------------------------------------------------------------------
# Physical constants: the `const.` namespace
# ---------------------------------------------------------------------------

# name -> (SI value, dimension). All linear; db(const.k_B) is how Boltzmann
# enters a link budget as the -228.6 dB(W/(K*Hz)) term — exactly, not by contract.
CONSTS: dict[str, tuple[float, Dim]] = {
    "const.pi": (math.pi, DIMENSIONLESS),
    "const.c0": (299792458.0, _d(m=1, s=-1)),  # speed of light
    "const.k_B": (1.380649e-23, _d(kg=1, m=2, s=-2, K=-1)),  # Boltzmann, J/K
    "const.h": (6.62607015e-34, _d(kg=1, m=2, s=-1)),  # Planck, J*s
    "const.g0": (9.80665, _d(m=1, s=-2)),  # standard gravity
}

FUNCTIONS = ("sqrt", "log10", "ln", "exp", "sin", "cos", "abs", "min", "max", "db", "lin")

VType = tuple[Dim, bool]  # (dimension, level flag)
_DIMLESS: VType = (DIMENSIONLESS, False)
_DB: VType = (DIMENSIONLESS, True)


# ---------------------------------------------------------------------------
# Canonical printing (the formula's content-addressed identity)
# ---------------------------------------------------------------------------

_PREC = {"+": 10, "-": 10, "*": 20, "/": 20, "^": 40}
_UNARY_PREC = 30


def _num(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


def format_expr(e: Expr, parent: int = 0, right_side: bool = False) -> str:
    if isinstance(e, ENum):
        s = _num(e.value) + (f" {e.unit}" if e.unit else "")
        # A united literal's unit is scanned greedily across * and / on re-parse,
        # so under any operator that binds at least as tight as * the literal is
        # parenthesized — "(3 m) / s" divides by a variable, "3 m / s" is a unit.
        return f"({s})" if e.unit and parent >= 20 else s
    if isinstance(e, ERef):
        return e.name
    if isinstance(e, ECall):
        return f"{e.fn}(" + ", ".join(format_expr(a) for a in e.args) + ")"
    if isinstance(e, EUn):
        inner = format_expr(e.x, _UNARY_PREC)
        s = f"-{inner}"
        return f"({s})" if parent > _UNARY_PREC else s
    assert isinstance(e, EBin)
    p = _PREC[e.op]
    ls = format_expr(e.l, p, False)
    # right operand needs parens at equal precedence for -, /, and ^ is right-assoc
    rp = p + (1 if e.op in ("-", "/") else 0)
    rs = format_expr(e.r, rp if e.op != "^" else p - 1, True)
    s = f"{ls} {e.op} {rs}"
    return f"({s})" if p < parent or (p == parent and right_side and e.op in ("-", "/")) else s


def format_stmt(s: ExprStmt) -> str:
    kw = "let " if s.is_let else ""
    return f"{kw}{s.target} = {format_expr(s.expr)}"


def canonical_body(stmts: list[ExprStmt]) -> str:
    """The content-addressed identity of an expr/stub core."""
    return "\n".join(format_stmt(s) for s in stmts)


# ---------------------------------------------------------------------------
# Type inference: dimensions + levels, before anything runs
# ---------------------------------------------------------------------------


def _vtype_of_unit(unit_text: str) -> Optional[VType]:
    try:
        u = parse_unit(unit_text)
        return (u.dim, u.level)
    except UnitError:
        return None


class _Infer:
    def __init__(self, node: str, env: dict[str, VType], bag: Bag):
        self.node = node
        self.env = env
        self.bag = bag
        self.ok = True

    def err(self, code: str, msg: str, span: Span, **kw) -> None:
        self.ok = False
        self.bag.error(code, f"{self.node}: {msg}", span, **kw)

    def expr(self, e: Expr) -> Optional[VType]:
        if isinstance(e, ENum):
            if not e.unit:
                return _DIMLESS
            t = _vtype_of_unit(e.unit)
            if t is None:
                self.err("UEL0301", f"unknown unit '{e.unit}' in expression literal", e.unit_span)
                return None
            return t
        if isinstance(e, ERef):
            if e.name in self.env:
                return self.env[e.name]
            if e.name in CONSTS:
                return (CONSTS[e.name][1], False)
            pool = list(self.env) + list(CONSTS)
            close = get_close_matches(e.name, pool, 1, 0.6)
            hint = f" — did you mean '{close[0]}'?" if close else ""
            reason = "expressions see knowns, params, earlier lets, earlier outputs, and const.*"
            # identifiers absorb internal hyphens (STR-014), so `a-b` is one name
            parts = e.name.split("-")
            if len(parts) > 1 and all(p in self.env or p in CONSTS for p in parts):
                hint = f" — did you mean '{' - '.join(parts)}'?"
                reason = ("identifiers may contain hyphens (STR-014), so subtraction "
                          "needs spaces: 'a - b'")
            self.err("UEL0310", f"unknown name '{e.name}' in expression{hint}", e.span,
                     reason=reason)
            return None
        if isinstance(e, EUn):
            t = self.expr(e.x)
            if t is None:
                return None
            d, lv = t
            return (dim_div(DIMENSIONLESS, d), True) if lv else t
        if isinstance(e, EBin):
            return self.binop(e)
        assert isinstance(e, ECall)
        return self.call(e)

    def binop(self, e: EBin) -> Optional[VType]:
        lt, rt = self.expr(e.l), self.expr(e.r)
        if e.op == "^":
            n = self._int_exponent(e.r)
            if lt is None or n is None:
                return None
            d, lv = lt
            if lv:
                self.err("UEL0312", "cannot raise a level to a power: in the linear domain "
                         "that is multiplication — write `n * x` on a dB quantity, or lin() first",
                         e.span)
                return None
            return (dim_pow(d, n), False)
        if lt is None or rt is None:
            return None
        (ld, llv), (rd, rlv) = lt, rt
        if e.op in ("+", "-"):
            if llv != rlv:
                lvl, lin = (("left", "right") if llv else ("right", "left"))
                self.err(
                    "UEL0311",
                    f"cannot {'add' if e.op == '+' else 'subtract'} a level and a linear quantity: "
                    f"{lvl} operand is {type_name(*(lt if llv else rt))}, {lin} operand is "
                    f"{type_name(*(rt if llv else lt))}",
                    e.span,
                    reason="cross the scales explicitly: db(x) makes a level, lin(x) a linear "
                           "quantity, and a literal like `0.2 dB` is already a level",
                )
                return None
            if llv:  # the one rule: levels add where linear quantities multiply
                return ((dim_mul if e.op == "+" else dim_div)(ld, rd), True)
            if ld != rd:
                self.err(
                    "UEL0311",
                    f"cannot {'add' if e.op == '+' else 'subtract'} {type_name(ld)} and {type_name(rd)}",
                    e.span,
                )
                return None
            return lt
        if e.op in ("*", "/"):
            if not llv and not rlv:
                return ((dim_mul if e.op == "*" else dim_div)(ld, rd), False)
            if rlv and e.op == "/":
                self.err("UEL0312", "cannot divide by a level quantity", e.span,
                         reason="convert with lin() first if a linear ratio is meant")
                return None
            lvl_t, lin_t = (lt, rt) if llv else (rt, lt)
            if lvl_t == _DB and lin_t == _DIMLESS:
                return _DB  # scaling a pure dB figure (20log10-style factors, array counts)
            self.err(
                "UEL0312",
                f"cannot {'multiply' if e.op == '*' else 'divide'} {type_name(*lvl_t)} by "
                f"{type_name(*lin_t)}: levels add; only a plain dB figure scales by a "
                "dimensionless factor",
                e.span,
                reason="to scale the underlying linear quantity, multiply before db(): "
                       "db(n * x), not n * db(x) — unless the dB-domain product is what you mean",
            )
            return None
        raise AssertionError(e.op)

    def _int_exponent(self, r: Expr) -> Optional[int]:
        if isinstance(r, EUn) and r.op == "-" and isinstance(r.x, ENum):
            r = ENum(-r.x.value, r.x.unit, r.x.unit_span, r.x.span)
        if not isinstance(r, ENum) or r.unit or abs(r.value - round(r.value)) > 1e-9:
            self.err("UEL0310", "'^' requires a literal integer exponent", getattr(r, "span", Span()),
                     reason="fractional powers of dimensioned quantities have no exact dimension; use sqrt()")
            return None
        n = int(round(r.value))
        if abs(n) > 12:
            self.err("UEL0310", f"exponent {n} is out of range (|n| <= 12)", r.span)
            return None
        return n

    def call(self, e: ECall) -> Optional[VType]:
        fn = e.fn
        if fn not in FUNCTIONS:
            close = get_close_matches(fn, FUNCTIONS, 1, 0.6)
            self.err("UEL0310", f"unknown function '{fn}'"
                     + (f" — did you mean '{close[0]}'?" if close else ""),
                     e.span, reason=f"expression functions: {', '.join(FUNCTIONS)}")
            return None
        want = 2 if fn in ("min", "max") else 1
        if (fn in ("min", "max") and len(e.args) < 2) or (fn not in ("min", "max") and len(e.args) != 1):
            self.err("UEL0310", f"{fn}() takes {'at least 2 arguments' if want == 2 else '1 argument'}, "
                     f"got {len(e.args)}", e.span)
            return None
        ts = [self.expr(a) for a in e.args]
        if any(t is None for t in ts):
            return None
        t0 = ts[0]
        assert t0 is not None
        d, lv = t0
        if fn in ("min", "max"):
            for t in ts[1:]:
                if t != t0:
                    self.err("UEL0311", f"{fn}() arguments differ in type: {type_name(*t0)} vs "
                             f"{type_name(*t)}", e.span)  # type: ignore[misc]
                    return None
            return t0
        if fn == "db":
            if lv:
                self.err("UEL0312", "db() argument is already a level", e.span)
                return None
            return (d, True)
        if fn == "lin":
            if not lv:
                self.err("UEL0312", "lin() argument is already linear", e.span)
                return None
            return (d, False)
        if lv:
            self.err("UEL0312", f"{fn}() does not apply to a level quantity; lin() first", e.span)
            return None
        if fn == "abs":
            return t0
        if fn == "sqrt":
            if any(x % 2 for x in d):
                self.err("UEL0311", f"sqrt of {type_name(d)} has no exact dimension — "
                         "restructure the formula", e.span)
                return None
            return (tuple(x // 2 for x in d), False)  # type: ignore[return-value]
        # log10 / ln / exp / sin / cos: pure-ratio (or angle) in, pure ratio out
        if d != DIMENSIONLESS:
            hint = ("angles are dimensionless (rad = 1); pass the angle itself"
                    if fn in ("sin", "cos")
                    else "divide by a reference first, or use db() for a level")
            self.err("UEL0311", f"{fn}() requires a dimensionless argument, got {type_name(d)}",
                     e.span, reason=hint)
            return None
        return _DIMLESS


def infer_program(
    node: str,
    stmts: list[ExprStmt],
    env0: dict[str, VType],
    outputs: dict[str, str],  # output name -> declared unit text
    bag: Bag,
    node_span: Span,
    stub: bool = False,
) -> bool:
    """Type-check an expr/stub core body. Returns True when clean.

    `env0` carries the types of knowns and params; outputs are assigned exactly
    once each, in order, and may be consumed by later statements.
    """
    inf = _Infer(node, dict(env0), bag)
    assigned: set[str] = set()
    kind = "stub" if stub else "expr"
    for s in stmts:
        literal = isinstance(s.expr, ENum) or (
            isinstance(s.expr, EUn) and s.expr.op == "-" and isinstance(s.expr.x, ENum)
        )
        if stub and not literal:
            inf.err("UEL0310", f"stub bodies are literal nominal values ('{s.target} = 4 dB'), "
                    "not formulas — promote the core to `expr` for arithmetic", s.span)
            continue
        t = inf.expr(s.expr)
        if s.is_let:
            if s.target in inf.env or s.target in outputs:
                inf.err("UEL0310", f"let '{s.target}' shadows an existing name", s.span)
                continue
            inf.env[s.target] = t if t is not None else _DIMLESS
            continue
        if s.target not in outputs:
            close = get_close_matches(s.target, list(outputs), 1, 0.6)
            inf.err("UEL0310", f"assignment target '{s.target}' is not a declared output"
                    + (f" — did you mean '{close[0]}'?" if close else ""),
                    s.span,
                    reason=f"a {kind} core assigns every declared output; intermediates use 'let'")
            continue
        if s.target in assigned:
            inf.err("UEL0310", f"output '{s.target}' assigned twice", s.span)
            continue
        assigned.add(s.target)
        declared = _vtype_of_unit(outputs[s.target])
        if t is not None and declared is not None and t != declared:
            inf.err(
                "UEL0311",
                f"output '{s.target}' is declared '{outputs[s.target] or 'dimensionless'}' "
                f"({type_name(*declared)}) but the expression computes {type_name(*t)}",
                s.span,
                reason="the declared output unit is the contract every consumer sees; "
                       "fix the formula or the declaration, whichever is lying",
            )
        inf.env[s.target] = declared if declared is not None else (t or _DIMLESS)
    for o in sorted(set(outputs) - assigned):
        inf.err("UEL0310", f"declared output '{o}' is never assigned", node_span)
    return inf.ok


# ---------------------------------------------------------------------------
# Evaluation: interval arithmetic over (lo, nominal, hi) in canonical SI
# ---------------------------------------------------------------------------

IV = tuple[float, float, float]


class ExprEvalError(Exception):
    def __init__(self, message: str, target: str = ""):
        super().__init__(message)
        self.target = target


def _iv(lo: float, nom: float, hi: float) -> IV:
    return (min(lo, hi), nom, max(lo, hi))


def _add(a: IV, b: IV) -> IV:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: IV, b: IV) -> IV:
    return (a[0] - b[2], a[1] - b[1], a[2] - b[0])


def _neg(a: IV) -> IV:
    return (-a[2], -a[1], -a[0])


def _mul(a: IV, b: IV) -> IV:
    ps = (a[0] * b[0], a[0] * b[2], a[2] * b[0], a[2] * b[2])
    return (min(ps), a[1] * b[1], max(ps))


def _div(a: IV, b: IV) -> IV:
    if b[0] <= 0.0 <= b[2]:
        raise ExprEvalError("division by an interval containing zero")
    return _mul(a, (1.0 / b[2], 1.0 / b[1], 1.0 / b[0]))


def _pow(a: IV, n: int) -> IV:
    if n == 0:
        return (1.0, 1.0, 1.0)
    if n < 0:
        return _div((1.0, 1.0, 1.0), _pow(a, -n))
    lo, nom, hi = a[0] ** n, a[1] ** n, a[2] ** n
    if n % 2 == 0 and a[0] < 0.0 < a[2]:
        return (0.0, nom, max(lo, hi))
    return _iv(lo, nom, hi)


def _mono(f, a: IV, domain_lo: float | None = None, what: str = "") -> IV:
    if domain_lo is not None and a[0] < domain_lo:
        raise ExprEvalError(f"{what} of a non-positive interval [{a[0]:g}, {a[2]:g}]")
    return (f(a[0]), f(a[1]), f(a[2]))


def _sqrt(a: IV) -> IV:
    if a[0] < -1e-12:
        raise ExprEvalError(f"sqrt of a negative interval [{a[0]:g}, {a[2]:g}]")
    return (math.sqrt(max(0.0, a[0])), math.sqrt(max(0.0, a[1])), math.sqrt(max(0.0, a[2])))


def _abs(a: IV) -> IV:
    if a[0] <= 0.0 <= a[2]:
        return (0.0, abs(a[1]), max(-a[0], a[2]))
    return _iv(abs(a[0]), abs(a[1]), abs(a[2]))


def _sin(a: IV) -> IV:
    lo, nom, hi = a
    if hi - lo >= 2.0 * math.pi:
        return (-1.0, math.sin(nom), 1.0)
    cands = [math.sin(lo), math.sin(hi)]
    k = math.ceil((lo - math.pi / 2.0) / math.pi)
    while math.pi / 2.0 + k * math.pi <= hi:
        cands.append(1.0 if k % 2 == 0 else -1.0)
        k += 1
    return (min(cands), math.sin(nom), max(cands))


def _cos(a: IV) -> IV:
    h = math.pi / 2.0
    return _sin((a[0] + h, a[1] + h, a[2] + h))


_CALLS = {
    "sqrt": _sqrt,
    "abs": _abs,
    "sin": _sin,
    "cos": _cos,
    "exp": lambda a: _mono(math.exp, a),
    "ln": lambda a: _mono(math.log, a, 0.0, "ln"),
    "log10": lambda a: _mono(math.log10, a, 0.0, "log10"),
    "db": lambda a: _mono(lambda v: 10.0 * math.log10(v), a, 0.0, "db"),
    "lin": lambda a: _mono(lambda v: 10.0 ** (v / 10.0), a),
}


def _eval(e: Expr, values: dict[str, IV]) -> IV:
    if isinstance(e, ENum):
        if e.unit:
            u = parse_unit(e.unit)  # inference already validated
            v = u.to_si(e.value)
        else:
            v = e.value
        return (v, v, v)
    if isinstance(e, ERef):
        if e.name in values:
            return values[e.name]
        c = CONSTS[e.name][0]
        return (c, c, c)
    if isinstance(e, EUn):
        return _neg(_eval(e.x, values))
    if isinstance(e, EBin):
        if e.op == "^":
            assert isinstance(e.r, (ENum, EUn))
            n = int(round(e.r.value)) if isinstance(e.r, ENum) else -int(round(e.r.x.value))  # type: ignore[union-attr]
            return _pow(_eval(e.l, values), n)
        a, b = _eval(e.l, values), _eval(e.r, values)
        if e.op == "+":
            return _add(a, b)
        if e.op == "-":
            return _sub(a, b)
        if e.op == "*":
            return _mul(a, b)
        return _div(a, b)
    assert isinstance(e, ECall)
    args = [_eval(a, values) for a in e.args]
    if e.fn == "min":
        return (min(a[0] for a in args), min(a[1] for a in args), min(a[2] for a in args))
    if e.fn == "max":
        return (max(a[0] for a in args), max(a[1] for a in args), max(a[2] for a in args))
    return _CALLS[e.fn](args[0])


def evaluate_program(
    stmts: list[ExprStmt], inputs: dict[str, IV], outputs: list[str]
) -> dict[str, IV]:
    """Run an expr/stub body over canonical-SI interval inputs.

    Raises ExprEvalError (with the offending statement's target) on domain
    errors — a diverged formula is a failed run, not a value (spec §4.4).
    """
    values = dict(inputs)
    result: dict[str, IV] = {}
    for s in stmts:
        try:
            v = _eval(s.expr, values)
        except ExprEvalError as ex:
            raise ExprEvalError(str(ex), s.target) from None
        if not all(math.isfinite(x) for x in v):
            raise ExprEvalError("expression produced a non-finite value", s.target)
        values[s.target] = v
        if not s.is_let and s.target in outputs:
            result[s.target] = v
    return result
