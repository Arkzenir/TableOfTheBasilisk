"""Canonical serialisation and hashing.

Everything that is hashed (events, snapshots, resolved packs) goes through
`canonical()`, so identical data produces identical bytes on every machine.
Floats are refused outright: the kernel is integer-only (§2.2).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class CanonicalError(TypeError):
    """Raised when data cannot be canonically serialised."""


def _check(obj: Any, path: str = "$") -> None:
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, str)):
        return
    if isinstance(obj, float):
        raise CanonicalError(f"float at {path}: the kernel is integer-only")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise CanonicalError(f"non-string key {k!r} at {path}")
            _check(v, f"{path}.{k}")
        return
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _check(v, f"{path}[{i}]")
        return
    raise CanonicalError(f"unsupported type {type(obj).__name__} at {path}")


def canonical(obj: Any) -> str:
    _check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str | bytes) -> str:
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def hash_obj(obj: Any) -> str:
    return sha256_hex(canonical(obj))
