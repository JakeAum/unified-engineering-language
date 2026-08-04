"""Canonical serialization.

One byte-stable JSON encoding, used by both the schema round-trip and content
hashing. Two invariants matter:

1. Same semantic object => same bytes, on any platform, forever within an edition.
   (sorted keys, fixed separators, UTF-8, shortest-round-trip float repr)
2. Empty/default fields are omitted, so a field that gains a value later changes
   the bytes exactly once, and absent-vs-default is not a hash-relevant distinction.

Floats are IEEE-754 doubles rendered by Python's shortest-round-trip repr; NaN and
infinities are not representable in the graph and are rejected here rather than
silently encoded.
"""

from __future__ import annotations

import json
import math


class CanonError(ValueError):
    """Raised when an object cannot be canonically encoded."""


def _validate(obj: object, path: str) -> None:
    if isinstance(obj, bool) or obj is None or isinstance(obj, (str, int)):
        return
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise CanonError(f"non-finite float at {path}")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise CanonError(f"non-string key {k!r} at {path}")
            _validate(v, f"{path}.{k}")
        return
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _validate(v, f"{path}[{i}]")
        return
    raise CanonError(f"unencodable type {type(obj).__name__} at {path}")


def canonical_str(obj: object) -> str:
    """Encode a plain object (dict/list/str/num/bool/None) canonically."""
    _validate(obj, "$")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_bytes(obj: object) -> bytes:
    return canonical_str(obj).encode("utf-8")


def pretty_str(obj: object) -> str:
    """Human-facing rendering; NOT canonical, never hashed."""
    _validate(obj, "$")
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)
