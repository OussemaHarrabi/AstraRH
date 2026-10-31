"""Canonical JSON and hashing: the basis of approval binding and the audit chain."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def _default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, UUID | Decimal):
        return str(value)
    raise TypeError(f"Not canonicalizable: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default
    )


def sha256_hex(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


def payload_hash(value: Any) -> str:
    return sha256_hex(canonical_json(value))
