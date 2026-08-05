"""Structured diagnostics — a first-class output of the compiler (program §4, Phase 2).

Agents iterate against errors, so every diagnostic carries: a stable code, a span,
a message stating what is wrong, a `reason` stating *why the rule exists* where that
isn't obvious, and — wherever mechanically possible — a `fix` an agent can apply
verbatim (`fix.replace` at `fix.span`, or `fix.hint` prose). The fix-loop conformance
kind grades exactly this: seeded errors must converge to a clean check by applying
emitted fixes.

Rendering: `--json` emits one object per diagnostic (schema below); human rendering
shows the source line with carets. Both derive from the same Diagnostic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Code registry. Codes are stable API within an edition; never renumber.
# ---------------------------------------------------------------------------

CODES: dict[str, str] = {
    # 00xx — project / io
    "UEL0001": "project error",
    "UEL0002": "io error",
    "UEL0003": "lockfile error",
    # 01xx — lexing / parsing
    "UEL0101": "unexpected token",
    "UEL0102": "unterminated string",
    "UEL0103": "malformed number",
    "UEL0104": "unexpected end of file",
    "UEL0105": "unknown item",
    "UEL0106": "duplicate field",
    "UEL0107": "malformed construct",
    # 02xx — resolution
    "UEL0201": "duplicate definition",
    "UEL0202": "unresolved reference",
    "UEL0203": "reference kind mismatch",
    "UEL0204": "dangling connection endpoint",
    "UEL0205": "malformed output reference",
    "UEL0206": "containment cycle",
    "UEL0207": "invalid binding",
    "UEL0208": "missing required declaration",
    # 03xx — units and dimensions
    "UEL0301": "unknown unit",
    "UEL0302": "dimension mismatch",
    "UEL0303": "affine unit composed",
    "UEL0304": "domain effort×flow is not power",
    "UEL0305": "port attribute dimension mismatch",
    "UEL0306": "malformed interval",
    "UEL0307": "budget dimension mismatch",
    "UEL0310": "expression error",
    "UEL0311": "expression dimension mismatch",
    "UEL0312": "illegal level operation",
    # 04xx — ports, conservation, budgets
    "UEL0401": "connection domain mismatch",
    "UEL0402": "connection direction conflict",
    "UEL0403": "static balance violation",
    "UEL0404": "effort window mismatch",
    "UEL0405": "budget exceeded",
    "UEL0406": "port never connected",
    # 05xx — envelopes
    "UEL0501": "envelope not covered",
    "UEL0502": "structural claim conflict",
    "UEL0503": "required claim not provided",
    "UEL0504": "unknown structural claim",
    "UEL0505": "envelope variable unit mismatch",
    # 06xx — geometry / DFM
    "UEL0601": "geometry without topological assertions",
    "UEL0602": "topological assertion failed",
    "UEL0603": "DFM rule violation",
    "UEL0604": "DFM check pending geometry run",
    # 07xx — identity / staleness / runtime
    "UEL0701": "stale node",
    "UEL0702": "lock out of date",
    "UEL0703": "core execution failed",
    "UEL0704": "core output does not match declaration",
    "UEL0705": "missing tolerance policy",
    # 08xx — calibration loop
    "UEL0801": "discrepancy: measurement outside predicted envelope",
    "UEL0802": "measurement target not found",
    "UEL0803": "measurement tightens envelope",

    "UEL0804": "output target violated",
    "UEL0805": "output target pending",
    "UEL0806": "seam value outside consumer fence",
    "UEL0807": "stub core in the graph",

    "UEL0808": "verification contract failed",
    "UEL0809": "verification contract pending",
}

SEVERITIES = ("error", "warning", "info")


@dataclass
class Span:
    file: str = ""
    line: int = 0  # 1-based; 0 = whole file / no location
    col: int = 0  # 1-based
    end_col: int = 0

    def to_obj(self) -> dict:
        o: dict = {"file": self.file}
        if self.line:
            o["line"] = self.line
        if self.col:
            o["col"] = self.col
        if self.end_col:
            o["end_col"] = self.end_col
        return o

    def __str__(self) -> str:
        if not self.line:
            return self.file or "<project>"
        if not self.col:
            return f"{self.file}:{self.line}"
        return f"{self.file}:{self.line}:{self.col}"


@dataclass
class Fix:
    """A mechanical fix an agent (or tool) can apply without judgment."""

    hint: str = ""  # prose instruction, always present when a fix exists
    replace: Optional[str] = None  # verbatim replacement text for span
    span: Optional[Span] = None  # where to apply `replace` (defaults to diagnostic span)

    def to_obj(self) -> dict:
        o: dict = {"hint": self.hint}
        if self.replace is not None:
            o["replace"] = self.replace
        if self.span is not None:
            o["span"] = self.span.to_obj()
        return o


@dataclass
class Diagnostic:
    code: str
    message: str
    span: Span = field(default_factory=Span)
    severity: str = "error"
    reason: str = ""  # why the rule exists / why this is a problem here
    fix: Optional[Fix] = None
    related: list[tuple[str, Span]] = field(default_factory=list)  # (note, where)

    def __post_init__(self) -> None:
        assert self.code in CODES, f"unregistered diagnostic code {self.code}"
        assert self.severity in SEVERITIES

    def to_obj(self) -> dict:
        o: dict = {
            "code": self.code,
            "title": CODES[self.code],
            "severity": self.severity,
            "message": self.message,
            "span": self.span.to_obj(),
        }
        if self.reason:
            o["reason"] = self.reason
        if self.fix:
            o["fix"] = self.fix.to_obj()
        if self.related:
            o["related"] = [{"note": n, "span": s.to_obj()} for n, s in self.related]
        return o


class Bag:
    """Diagnostic accumulator shared across compiler stages."""

    def __init__(self) -> None:
        self.items: list[Diagnostic] = []

    def add(self, diag: Diagnostic) -> None:
        self.items.append(diag)

    def error(self, code: str, message: str, span: Span | None = None, **kw) -> None:
        self.add(Diagnostic(code, message, span or Span(), "error", **kw))

    def warning(self, code: str, message: str, span: Span | None = None, **kw) -> None:
        self.add(Diagnostic(code, message, span or Span(), "warning", **kw))

    def info(self, code: str, message: str, span: Span | None = None, **kw) -> None:
        self.add(Diagnostic(code, message, span or Span(), "info", **kw))

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity == "error"]

    def ok(self) -> bool:
        return not self.errors

    # Lock-derived verdicts (a violated target, a seam value outside its fence,
    # a failed cross-check) compare computed state against declared intent: they
    # red-gate a merge, but they must not gate the scheduler — only a rebuild
    # can refresh the very values they complain about.
    _RESULT_CODES = ("UEL0804", "UEL0806", "UEL0808")

    def gates_runtime(self) -> bool:
        return any(d.code not in self._RESULT_CODES for d in self.errors)

    def extend(self, other: "Bag") -> None:
        self.items.extend(other.items)

    def sorted(self) -> list[Diagnostic]:
        sev_rank = {"error": 0, "warning": 1, "info": 2}
        return sorted(
            self.items,
            key=lambda d: (d.span.file, d.span.line, d.span.col, sev_rank[d.severity], d.code),
        )

    # -- rendering --

    def to_json(self) -> str:
        return json.dumps([d.to_obj() for d in self.sorted()], indent=2, ensure_ascii=False)

    def render(self, sources: dict[str, str] | None = None, color: bool = False) -> str:
        """Human rendering. `sources` maps file path -> content for excerpts."""
        out: list[str] = []
        for d in self.sorted():
            head = f"{d.severity} [{d.code}] {d.message}"
            out.append(head)
            out.append(f"  --> {d.span}")
            if sources and d.span.file in sources and d.span.line:
                lines = sources[d.span.file].splitlines()
                if 0 < d.span.line <= len(lines):
                    text = lines[d.span.line - 1]
                    out.append(f"   | {text}")
                    if d.span.col:
                        width = max(1, (d.span.end_col or d.span.col + 1) - d.span.col)
                        out.append("   | " + " " * (d.span.col - 1) + "^" * width)
            if d.reason:
                out.append(f"  reason: {d.reason}")
            if d.fix:
                out.append(f"  fix: {d.fix.hint}")
                if d.fix.replace is not None:
                    out.append(f"       replace with: {d.fix.replace}")
            for note, where in d.related:
                out.append(f"  note: {note} ({where})")
            out.append("")
        counts: dict[str, int] = {}
        for d in self.items:
            counts[d.severity] = counts.get(d.severity, 0) + 1
        if self.items:
            out.append(
                "; ".join(f"{v} {k}{'s' if v != 1 else ''}" for k, v in sorted(counts.items()))
            )
        return "\n".join(out)
