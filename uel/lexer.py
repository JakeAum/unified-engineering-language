"""Lexer for the UEL surface syntax.

Design notes (spec §5.1): plain text, line-oriented, diff-friendly. All keywords are
contextual — the lexer emits IDENT and the parser matches by value, so no domain
word ('flow', 'model', 'text', …) is stolen from users.

Identifier rule: identifiers may contain internal hyphens when both neighbors are
alphanumeric (`STR-014`), because v0.1 has no arithmetic expressions and the only
uses of '-' are negative number literals and arrows. `±` may be written `+-`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .diagnostics import Bag, Span


class T(Enum):
    IDENT = "ident"
    NUMBER = "number"
    STRING = "string"
    LBRACE = "{"
    RBRACE = "}"
    LBRACKET = "["
    RBRACKET = "]"
    LPAREN = "("
    RPAREN = ")"
    COLON = ":"
    SEMI = ";"
    COMMA = ","
    DOT = "."
    EQ = "="
    ARROW_R = "->"
    ARROW_L = "<-"
    LE = "<="
    GE = ">="
    LT = "<"
    GT = ">"
    PM = "±"
    AT = "@"
    CARET = "^"
    STAR = "*"
    SLASH = "/"
    MINUS = "-"
    PERCENT = "%"
    NEWLINE = "\\n"
    EOF = "eof"


@dataclass
class Token:
    kind: T
    text: str
    line: int  # 1-based
    col: int  # 1-based
    value: float | None = None  # NUMBER only

    def span(self, file: str) -> Span:
        return Span(file, self.line, self.col, self.col + max(1, len(self.text)))


@dataclass
class Comment:
    line: int
    col: int
    text: str  # without leading '#', stripped
    own_line: bool  # True when nothing but whitespace precedes it on the line


_PUNCT2 = {"->": T.ARROW_R, "<-": T.ARROW_L, "<=": T.LE, ">=": T.GE, "+-": T.PM}
_PUNCT1 = {
    "{": T.LBRACE, "}": T.RBRACE, "[": T.LBRACKET, "]": T.RBRACKET,
    "(": T.LPAREN, ")": T.RPAREN, ":": T.COLON, ";": T.SEMI, ",": T.COMMA,
    ".": T.DOT, "=": T.EQ, "<": T.LT, ">": T.GT, "±": T.PM, "@": T.AT,
    "^": T.CARET, "*": T.STAR, "/": T.SLASH, "-": T.MINUS, "%": T.PERCENT,
}

_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def _is_ident_start(c: str) -> bool:
    return c.isalpha() or c == "_"


def _is_ident_char(c: str) -> bool:
    return c.isalnum() or c == "_"


def lex(text: str, file: str, bag: Bag) -> tuple[list[Token], list[Comment]]:
    tokens: list[Token] = []
    comments: list[Comment] = []
    line, col = 1, 1
    i, n = 0, len(text)
    line_had_token = False

    def add(kind: T, s: str, ln: int, cl: int, value: float | None = None) -> None:
        tokens.append(Token(kind, s, ln, cl, value))

    while i < n:
        c = text[i]
        # newline
        if c == "\n":
            if tokens and tokens[-1].kind != T.NEWLINE:
                add(T.NEWLINE, "\n", line, col)
            i += 1
            line += 1
            col = 1
            line_had_token = False
            continue
        # whitespace
        if c in " \t\r":
            i += 1
            col += 1
            continue
        # comment to EOL
        if c == "#":
            start_col = col
            j = i
            while j < n and text[j] != "\n":
                j += 1
            comments.append(Comment(line, start_col, text[i + 1:j].strip(), not line_had_token))
            col += j - i
            i = j
            continue
        line_had_token = True
        # string
        if c == '"':
            ln, cl = line, col
            j = i + 1
            out: list[str] = []
            terminated = False
            while j < n:
                ch = text[j]
                if ch == "\n":
                    break
                if ch == "\\":
                    if j + 1 < n and text[j + 1] in _ESCAPES:
                        out.append(_ESCAPES[text[j + 1]])
                        j += 2
                        continue
                    bag.error("UEL0102", f"unknown escape '\\{text[j+1] if j+1 < n else ''}'",
                              Span(file, line, col + (j - i)),
                              reason="strings support \\n, \\t, \\\" and \\\\ only")
                    j += 2
                    continue
                if ch == '"':
                    terminated = True
                    j += 1
                    break
                out.append(ch)
                j += 1
            if not terminated:
                bag.error("UEL0102", "unterminated string literal", Span(file, ln, cl))
            add(T.STRING, "".join(out), ln, cl)
            col += j - i
            i = j
            continue
        # number (digit-leading; parser owns unary minus)
        if c.isdigit():
            ln, cl = line, col
            j = i
            while j < n and text[j].isdigit():
                j += 1
            if j < n and text[j] == "." and j + 1 < n and text[j + 1].isdigit():
                j += 1
                while j < n and text[j].isdigit():
                    j += 1
            if j < n and text[j] in "eE":
                k = j + 1
                if k < n and text[k] in "+-":
                    k += 1
                if k < n and text[k].isdigit():
                    j = k
                    while j < n and text[j].isdigit():
                        j += 1
            raw = text[i:j]
            # trailing garbage like 12.5.3 or 1x
            if j < n and (text[j] == "." and j + 1 < n and text[j + 1].isdigit()):
                while j < n and (text[j].isdigit() or text[j] == "."):
                    j += 1
                raw = text[i:j]
                bag.error("UEL0103", f"malformed number '{raw}'", Span(file, ln, cl, cl + len(raw)))
                add(T.NUMBER, raw, ln, cl, 0.0)
            else:
                add(T.NUMBER, raw, ln, cl, float(raw))
            col += j - i
            i = j
            continue
        # identifier (with internal-hyphen rule)
        if _is_ident_start(c):
            ln, cl = line, col
            j = i
            while j < n and _is_ident_char(text[j]):
                j += 1
            while (
                j < n
                and text[j] == "-"
                and j + 1 < n
                and _is_ident_char(text[j + 1])
                and _is_ident_char(text[j - 1])
            ):
                j += 1
                while j < n and _is_ident_char(text[j]):
                    j += 1
            raw = text[i:j]
            add(T.IDENT, raw, ln, cl)
            col += j - i
            i = j
            continue
        # two-char punctuation
        if i + 1 < n and text[i:i + 2] in _PUNCT2:
            add(_PUNCT2[text[i:i + 2]], text[i:i + 2], line, col)
            i += 2
            col += 2
            continue
        # one-char punctuation
        if c in _PUNCT1:
            add(_PUNCT1[c], c, line, col)
            i += 1
            col += 1
            continue
        bag.error("UEL0101", f"unexpected character {c!r}", Span(file, line, col))
        i += 1
        col += 1

    add(T.EOF, "", line, col)
    return tokens, comments
