"""Canonical serialization: one byte-stable JSON encoding for round-trip and
hashing. Same semantic object => same bytes (sorted keys, fixed separators,
shortest-round-trip floats); NaN/Inf are rejected, never encoded; empty fields
are omitted upstream so absent-vs-default is not a hash-relevant distinction."""

from __future__ import annotations

import json
import math

class CanonError(ValueError):
    """Raised when an object cannot be canonically encoded."""

def _validate(obj: object, path: str) -> None:
    if isinstance(obj, bool) or obj is None or isinstance(obj, (str, int)): return
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj): raise CanonError(f"non-finite float at {path}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str): raise CanonError(f"non-string key {k!r} at {path}")
            _validate(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _validate(v, f"{path}[{i}]")
    else:
        raise CanonError(f"unencodable type {type(obj).__name__} at {path}")

def canonical_str(obj: object) -> str:
    _validate(obj, "$")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def canonical_bytes(obj: object) -> bytes:
    return canonical_str(obj).encode("utf-8")

def pretty_str(obj: object) -> str:
    """Human-facing rendering; NOT canonical, never hashed."""
    _validate(obj, "$")
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)
