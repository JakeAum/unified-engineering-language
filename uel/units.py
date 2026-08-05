"""Units and dimensions: a Kennedy-style free-abelian-group checker.

A dimension is a vector of integer exponents over eight base dimensions:

    (mass, length, time, current, temperature, amount, luminosity, currency)

Multiplication of quantities adds vectors; division subtracts; comparison demands
equality. Angle is dimensionless by decision (rad = 1, deg = π/180) so that
torque × angular-velocity = power holds without a pseudo-dimension; this is the
standard SI convention and is recorded in the unit table, not hard-coded logic.
Currency is a first-class base dimension because cost is a flowing quantity of the
one graph (spec §7.3); USD is its base unit in v0.1.

Affine units (degC) carry an offset and are only legal standalone — composing or
prefixing an affine unit is a hard error (UEL0303) because `K/W` means something and
`degC/W` does not.

**Level units (v0.2, ADR-0006).** A level is `10·log10` of a linear quantity
against an SI-coherent reference: `dBW` is a level of power, `dBHz` a level of
frequency, `dB` the level of a dimensionless ratio. A level's *type* is the
referenced linear dimension plus the level flag; its canonical scale is
"dB re the SI-coherent unit", so `dBm` converts by an additive −30. Composing a
level with a linear unit shifts the reference (`dB/K` ≡ level of 1/K;
`dBW/(K*Hz)` ≡ level of W/(K·Hz)); composing two levels, exponentiating a level,
or dividing a linear unit by a level has no affine-map meaning and is an error.
Arithmetic between level *values* lives in the expression layer (uel.expr):
levels add where linear quantities multiply.

The unit table is data. Libraries may extend it in later versions; v0.1 ships the
SI-plus-engineering set below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Optional

N_BASE = 8
BASE_NAMES = ("kg", "m", "s", "A", "K", "mol", "cd", "USD")

Dim = tuple[int, int, int, int, int, int, int, int]

DIMENSIONLESS: Dim = (0,) * N_BASE

def dim_mul(a: Dim, b: Dim) -> Dim:
    return tuple(x + y for x, y in zip(a, b))  # type: ignore[return-value]

def dim_div(a: Dim, b: Dim) -> Dim:
    return tuple(x - y for x, y in zip(a, b))  # type: ignore[return-value]

def dim_pow(a: Dim, n: int) -> Dim:
    return tuple(x * n for x in a)  # type: ignore[return-value]

def dim_str(d: Dim) -> str:
    """Human name of a dimension vector, e.g. 'kg*m/s^2'."""
    if d == DIMENSIONLESS: return "dimensionless"
    num, den = [], []
    for name, e in zip(BASE_NAMES, d):
        if e > 0:
            num.append(name if e == 1 else f"{name}^{e}")
        elif e < 0:
            den.append(name if e == -1 else f"{name}^{-e}")
    s = "*".join(num) if num else "1"
    if den:
        s += "/" + "/".join(den)
    return s

def _d(kg=0, m=0, s=0, A=0, K=0, mol=0, cd=0, USD=0) -> Dim:
    return (kg, m, s, A, K, mol, cd, USD)

# Well-known derived dimensions, used in messages and domain checks.
D_MASS = _d(kg=1)
D_LENGTH = _d(m=1)
D_TIME = _d(s=1)
D_CURRENT = _d(A=1)
D_TEMP = _d(K=1)
D_CURRENCY = _d(USD=1)
D_AREA = _d(m=2)
D_VOLUME = _d(m=3)
D_FORCE = _d(kg=1, m=1, s=-2)
D_PRESSURE = _d(kg=1, m=-1, s=-2)
D_ENERGY = _d(kg=1, m=2, s=-2)
D_POWER = _d(kg=1, m=2, s=-3)
D_VOLTAGE = _d(kg=1, m=2, s=-3, A=-1)
D_FREQ = _d(s=-1)

_WELL_KNOWN = {
    DIMENSIONLESS: "dimensionless",
    D_MASS: "mass",
    D_LENGTH: "length",
    D_TIME: "time",
    D_CURRENT: "current",
    D_TEMP: "temperature",
    D_CURRENCY: "currency",
    D_AREA: "area",
    D_VOLUME: "volume",
    D_FORCE: "force",
    D_PRESSURE: "pressure/stress",
    D_ENERGY: "energy",
    D_POWER: "power",
    D_VOLTAGE: "voltage",
    D_FREQ: "frequency",
}

def dim_name(d: Dim) -> str:
    known = _WELL_KNOWN.get(d)
    return f"{known} ({dim_str(d)})" if known and d != DIMENSIONLESS else dim_str(d)

def type_name(d: Dim, level: bool = False) -> str:
    """Human name of a full quantity type: dimension + level flag."""
    if not level: return dim_name(d)
    if d == DIMENSIONLESS: return "level (dB, a log ratio)"
    return f"level (dB re {dim_str(d)})"

@dataclass(frozen=True)
class UnitDef:
    factor: float  # multiply by this to reach SI-coherent value
    dim: Dim
    offset: float = 0.0  # affine units only (to SI: v*factor + offset)
    prefixable: bool = False
    level: bool = False  # log-referenced level unit (dB family); offset is the dB shift

    @property
    def affine(self) -> bool:
        return self.offset != 0.0 and not self.level

_PI = 3.141592653589793

# name -> UnitDef. The table is the vocabulary; the group law is the checker.
UNITS: dict[str, UnitDef] = {
    # SI base (gram is the prefixable mass symbol; kg = k+g arrives via prefix)
    "g": UnitDef(1e-3, D_MASS, prefixable=True),
    "m": UnitDef(1.0, D_LENGTH, prefixable=True),
    "s": UnitDef(1.0, D_TIME, prefixable=True),
    "A": UnitDef(1.0, D_CURRENT, prefixable=True),
    "K": UnitDef(1.0, D_TEMP, prefixable=True),
    "mol": UnitDef(1.0, _d(mol=1), prefixable=True),
    "cd": UnitDef(1.0, _d(cd=1)),
    "USD": UnitDef(1.0, D_CURRENCY),
    # SI derived
    "N": UnitDef(1.0, D_FORCE, prefixable=True),
    "Pa": UnitDef(1.0, D_PRESSURE, prefixable=True),
    "J": UnitDef(1.0, D_ENERGY, prefixable=True),
    "W": UnitDef(1.0, D_POWER, prefixable=True),
    "V": UnitDef(1.0, D_VOLTAGE, prefixable=True),
    "ohm": UnitDef(1.0, _d(kg=1, m=2, s=-3, A=-2), prefixable=True),
    "F": UnitDef(1.0, _d(kg=-1, m=-2, s=4, A=2), prefixable=True),
    "H": UnitDef(1.0, _d(kg=1, m=2, s=-2, A=-2), prefixable=True),
    "Hz": UnitDef(1.0, D_FREQ, prefixable=True),
    "C": UnitDef(1.0, _d(s=1, A=1), prefixable=True),
    "Wb": UnitDef(1.0, _d(kg=1, m=2, s=-2, A=-1)),
    "T": UnitDef(1.0, _d(kg=1, s=-2, A=-1)),
    # angle: dimensionless by decision (see module docstring)
    "rad": UnitDef(1.0, DIMENSIONLESS),
    "deg": UnitDef(_PI / 180.0, DIMENSIONLESS),
    "rev": UnitDef(2.0 * _PI, DIMENSIONLESS),
    # decibels: LEVEL units (v0.2, ADR-0006). The type is the referenced linear
    # dimension + the level flag; the canonical scale is dB re the SI-coherent
    # unit, so conversion between level units of one dimension is additive
    # (dBm -> dBW is -30). `dB` is the level of a dimensionless ratio (gains,
    # losses, margins); `dBi` is the same type, named for the isotropic reference.
    "dB": UnitDef(1.0, DIMENSIONLESS, level=True),
    "dBi": UnitDef(1.0, DIMENSIONLESS, level=True),
    "dBW": UnitDef(1.0, D_POWER, level=True),
    "dBm": UnitDef(1.0, D_POWER, offset=-30.0, level=True),  # dB re mW
    "dBHz": UnitDef(1.0, D_FREQ, level=True),
    "dBK": UnitDef(1.0, D_TEMP, level=True),
    # time, engineering
    "min": UnitDef(60.0, D_TIME),
    "hr": UnitDef(3600.0, D_TIME),
    "day": UnitDef(86400.0, D_TIME),
    "week": UnitDef(604800.0, D_TIME),
    "rpm": UnitDef(2.0 * _PI / 60.0, D_FREQ),  # rev/min as angular rate
    # volume, pressure, misc engineering
    "L": UnitDef(1e-3, D_VOLUME, prefixable=True),
    "bar": UnitDef(1e5, D_PRESSURE, prefixable=True),
    "t": UnitDef(1e3, D_MASS),  # metric tonne
    "gee": UnitDef(9.80665, _d(m=1, s=-2)),  # standard gravity as acceleration unit
    # affine temperatures (standalone only)
    "degC": UnitDef(1.0, D_TEMP, offset=273.15),
    "degF": UnitDef(5.0 / 9.0, D_TEMP, offset=459.67 * 5.0 / 9.0),
}

PREFIXES: dict[str, float] = {
    "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "c": 1e-2, "d": 1e-1,
    "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12,
}

class UnitError(ValueError):
    def __init__(self, message: str, suggestion: Optional[str] = None):
        super().__init__(message)
        self.suggestion = suggestion

# Longhand and common misspellings -> canonical symbol. Keys lowercase; the table
# exists so that did-you-mean fixes are machine-applicable (fix-loop discipline).
_ALIASES: dict[str, str] = {
    "watt": "W", "watts": "W",
    "gram": "g", "grams": "g", "gramme": "g", "grammes": "g",
    "kilogram": "kg", "kilograms": "kg", "kilo": "kg",
    "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "millimeter": "mm", "millimeters": "mm", "millimetre": "mm",
    "second": "s", "seconds": "s", "sec": "s",
    "minute": "min", "minutes": "min",
    "hour": "hr", "hours": "hr", "h": "hr",
    "days": "day", "weeks": "week",
    "amp": "A", "amps": "A", "ampere": "A", "amperes": "A",
    "volt": "V", "volts": "V",
    "newton": "N", "newtons": "N",
    "joule": "J", "joules": "J",
    "pascal": "Pa", "pascals": "Pa",
    "kelvin": "K",
    "celsius": "degC", "centigrade": "degC", "c": "degC",
    "fahrenheit": "degF",
    "hertz": "Hz",
    "ohms": "ohm",
    "liter": "L", "liters": "L", "litre": "L", "litres": "L",
    "dollar": "USD", "dollars": "USD", "usd": "USD",
    "degree": "deg", "degrees": "deg",
    "radian": "rad", "radians": "rad",
    "revs": "rev", "revolutions": "rev",
    "tonne": "t", "tonnes": "t", "ton": "t",
    "db": "dB", "dbw": "dBW", "dbm": "dBm", "dbhz": "dBHz", "dbi": "dBi", "dbk": "dBK",
}

def _lookup_symbol(sym: str) -> UnitDef:
    """Exact symbol first, then prefix + prefixable symbol, then aliases."""
    if sym in UNITS: return UNITS[sym]
    for plen in (1,):  # all prefixes are single-character
        p, rest = sym[:plen], sym[plen:]
        if p in PREFIXES and rest in UNITS and UNITS[rest].prefixable:
            base = UNITS[rest]
            if base.affine: raise UnitError(f"affine unit '{rest}' cannot take a prefix")
            return UnitDef(PREFIXES[p] * base.factor, base.dim)
    # suggestion machinery
    alias = _ALIASES.get(sym.lower())
    if alias: raise UnitError(f"unknown unit '{sym}'", suggestion=alias)
    candidates = sorted(
        set(list(UNITS) + list(_ALIASES)
            + [p + u for p in ("k", "m", "M", "u") for u, d in UNITS.items() if d.prefixable])
    )
    close = get_close_matches(sym, candidates, n=1, cutoff=0.6)
    suggestion = None
    if close:
        suggestion = _ALIASES.get(close[0].lower(), close[0]) if close[0] not in UNITS else close[0]
        if suggestion not in UNITS and close[0] in _ALIASES:
            suggestion = _ALIASES[close[0]]
    raise UnitError(f"unknown unit '{sym}'", suggestion=suggestion)

@dataclass(frozen=True)
class Unit:
    """A resolved unit expression: canonical text + conversion + dimension.

    Level units (dB family) use the same affine map to reach canonical form —
    factor 1.0 and an additive dB shift in `offset` — but carry `level=True`:
    type equality is (dim, level), and canonical SI form is "dB re SI-coherent".
    """

    text: str  # canonical surface form, e.g. "kN", "kg/m^3", "" for dimensionless
    factor: float
    dim: Dim
    offset: float = 0.0
    level: bool = False

    @property
    def affine(self) -> bool:
        return self.offset != 0.0 and not self.level

    @property
    def vtype(self) -> tuple[Dim, bool]:
        """The quantity type this unit measures: (dimension, level flag)."""
        return (self.dim, self.level)

    def to_si(self, v: float) -> float:
        return v * self.factor + self.offset

    def from_si(self, v: float) -> float:
        return (v - self.offset) / self.factor

DIMENSIONLESS_UNIT = Unit("", 1.0, DIMENSIONLESS)

class _UnitParser:
    """unit_expr := term (('*'|'/') term)* ; term := factor ('^' int)? ;
    factor := SYMBOL | '(' unit_expr ')' — whitespace-free surface strings.

    Each production yields (factor, dim, offset, level). Level composition
    (ADR-0006): level ∘ linear shifts the reference additively; level ∘ level,
    level^n, and linear/level are errors — no affine map realizes them.
    """

    def __init__(self, text: str):
        self.text = text
        self.i = 0

    def error(self, msg: str, suggestion: str | None = None):
        raise UnitError(f"{msg} in unit expression '{self.text}'", suggestion)

    def peek(self) -> str:
        return self.text[self.i] if self.i < len(self.text) else ""

    def _combine(self, a, op: str, b):
        f1, d1, off1, lv1 = a
        f2, d2, off2, lv2 = b
        if lv1 and lv2:
            raise UnitError(
                f"cannot combine two level units in '{self.text}': levels add as values, not as units"
            )
        if (off1 != 0.0 and not lv1) or (off2 != 0.0 and not lv2):
            raise UnitError(f"affine unit composed in '{self.text}'")
        if lv2 and op == "/":
            raise UnitError(
                f"cannot divide by a level unit in '{self.text}': 1/dB has no meaning as a unit"
            )
        if lv1 or lv2:
            # exactly one side is a level; the linear side shifts the reference
            lin_f = f2 if lv1 else f1
            shift = (off1 if lv1 else off2)
            log_shift = 10.0 * math.log10(lin_f)
            if op == "*": return 1.0, dim_mul(d1, d2), shift + log_shift, True
            return 1.0, dim_div(d1, d2), shift - log_shift, True
        if op == "*": return f1 * f2, dim_mul(d1, d2), 0.0, False
        return f1 / f2, dim_div(d1, d2), 0.0, False

    def parse(self) -> tuple[float, Dim, float, bool, bool]:
        """Returns (factor, dim, offset, level, is_composite)."""
        cur = self.parse_term()
        composite = False
        while self.peek() in ("*", "/"):
            composite = True
            op = self.text[self.i]
            self.i += 1
            cur = self._combine(cur, op, self.parse_term())
        if self.i != len(self.text):
            self.error(f"unexpected character '{self.peek()}'")
        f, d, off, lv = cur
        return f, d, off, lv, composite

    def parse_term(self) -> tuple[float, Dim, float, bool]:
        f, d, off, lv = self.parse_factor()
        if self.peek() == "^":
            self.i += 1
            neg = False
            if self.peek() == "-":
                neg = True
                self.i += 1
            start = self.i
            while self.peek().isdigit():
                self.i += 1
            if start == self.i:
                self.error("expected integer exponent after '^'")
            n = int(self.text[start:self.i]) * (-1 if neg else 1)
            if lv:
                raise UnitError(
                    f"cannot raise a level unit to a power in '{self.text}': "
                    "exponentiation of a level is multiplication of its value"
                )
            if off != 0.0: raise UnitError(f"affine unit composed in '{self.text}'")
            f, d = f**n, dim_pow(d, n)
        return f, d, off, lv

    def parse_factor(self) -> tuple[float, Dim, float, bool]:
        if self.peek() == "(":
            self.i += 1
            f, d, off, lv, _ = _UnitParser(self._until_close()).parse()
            return f, d, off, lv
        start = self.i
        while self.peek().isalnum() or self.peek() in ("_", "µ"):
            self.i += 1
        if start == self.i:
            self.error("expected unit symbol")
        sym = self.text[start:self.i]
        u = _lookup_symbol(sym)
        return u.factor, u.dim, u.offset, u.level

    def _until_close(self) -> str:
        depth, start = 1, self.i
        while self.i < len(self.text):
            c = self.text[self.i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    inner = self.text[start:self.i]
                    self.i += 1
                    return inner
            self.i += 1
        self.error("unclosed '(' ")
        raise AssertionError

def parse_unit(text: str) -> Unit:
    """Parse a surface unit expression into a resolved Unit.

    '' and 'dimensionless' are the dimensionless unit. Raises UnitError with an
    optional did-you-mean suggestion.
    """
    text = text.strip()
    if text in ("", "dimensionless", "1"): return DIMENSIONLESS_UNIT
    compact = text.replace(" ", "")
    f, d, off, lv, composite = _UnitParser(compact).parse()
    if off != 0.0 and composite and not lv: raise UnitError(f"affine unit composed in '{text}'")
    return Unit(compact, f, d, off, lv)

def is_unit_symbol(sym: str) -> bool:
    """True iff `sym` resolves as a unit symbol (exact or prefixed; aliases are
    suggestions, not units). Used by the expression parser to decide whether an
    identifier after a numeric literal is a unit or an operand."""
    try:
        _lookup_symbol(sym)
        return True
    except UnitError:
        return False

def check_effort_flow_power(effort_unit: str, flow_unit: str) -> bool:
    """Kernel invariant for power domains: dim(effort) * dim(flow) == power."""
    eu, fu = parse_unit(effort_unit), parse_unit(flow_unit)
    return not eu.level and not fu.level and dim_mul(eu.dim, fu.dim) == D_POWER
