"""Canonical serialization used for reproducible product artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import BaseModel


def _normalize(value: Any) -> Any:
    """Return JSON-compatible data with deterministic ordering.

    Pydantic already handles most values, but this function is intentionally
    usable for repository payloads and plain nested mappings too.
    """

    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _normalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple, set, frozenset)):
        values = [_normalize(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return sorted(values, key=lambda item: json.dumps(item, sort_keys=True))
        return values
    if isinstance(value, Enum):
        return _normalize(value.value)
    return value


def canonical_payload(value: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    """Build a recursively sorted JSON-compatible payload."""

    normalized = _normalize(value)
    if not isinstance(normalized, dict):
        raise TypeError("canonical payload must be an object")
    return normalized


def canonical_json(value: BaseModel | Mapping[str, Any]) -> str:
    """Serialize a contract without whitespace or key-order ambiguity."""

    return json.dumps(
        canonical_payload(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_sha256(value: BaseModel | Mapping[str, Any]) -> str:
    """Return the SHA-256 digest of the canonical JSON representation."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
