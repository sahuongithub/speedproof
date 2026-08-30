"""Canonical serialisation for output equivalence.

Equality is decided by hashing a harness-owned byte encoding, never by calling
``__eq__`` on a value produced by the code under test.  A patch that overrides
equality, or that returns a proxy object which compares equal to everything,
cannot influence the verdict.
"""

from __future__ import annotations

import hashlib
from typing import Any

_MAX_DEPTH = 64


class Unencodable(Exception):
    """Raised when a value has no stable canonical encoding."""


def encode(value: Any, _depth: int = 0) -> bytes:
    """Encode ``value`` as bytes that depend only on its structure and contents.

    Ordering is made explicit for sets and mappings so that two runs which
    build the same logical value in a different order still encode identically.
    """
    if _depth > _MAX_DEPTH:
        raise Unencodable("value nests deeper than the encoder will follow")

    if value is None:
        return b"N"
    if value is True:
        return b"B1"
    if value is False:
        return b"B0"
    if isinstance(value, int):
        return b"I" + repr(value).encode()
    if isinstance(value, float):
        # repr round-trips exactly for float; NaN and infinities encode stably.
        return b"F" + repr(value).encode()
    if isinstance(value, str):
        return b"S" + value.encode("utf-8", "surrogatepass")
    if isinstance(value, (bytes, bytearray)):
        return b"Y" + bytes(value)
    if isinstance(value, (list, tuple)):
        tag = b"L" if isinstance(value, list) else b"T"
        parts = [tag, repr(len(value)).encode()]
        for item in value:
            chunk = encode(item, _depth + 1)
            parts.append(repr(len(chunk)).encode())
            parts.append(chunk)
        return b"".join(parts)
    if isinstance(value, (set, frozenset)):
        chunks = sorted(encode(item, _depth + 1) for item in value)
        parts = [b"E", repr(len(chunks)).encode()]
        for chunk in chunks:
            parts.append(repr(len(chunk)).encode())
            parts.append(chunk)
        return b"".join(parts)
    if isinstance(value, dict):
        chunks = sorted(
            encode(k, _depth + 1) + b"=" + encode(v, _depth + 1)
            for k, v in value.items()
        )
        parts = [b"D", repr(len(chunks)).encode()]
        for chunk in chunks:
            parts.append(repr(len(chunk)).encode())
            parts.append(chunk)
        return b"".join(parts)

    raise Unencodable(f"no canonical encoding for {type(value).__name__}")


def checksum(value: Any) -> str:
    """Return a hex digest of ``value``'s canonical encoding."""
    return hashlib.sha256(encode(value)).hexdigest()
