"""Outbound adapters. Only the executor may import this package; a test enforces it."""

from typing import Any

from kernel.adapters import mail
from kernel.trust import AdapterRejected

_RUNNERS = {"email.send": mail.send}
_LOOKUPS = {"email.send": mail.find}


def run(adapter: str | None, payload: dict[str, Any], key: str) -> str | None:
    runner = _RUNNERS.get(adapter or "")
    if runner is None:
        raise AdapterRejected(f"Unknown adapter {adapter}")
    return runner(payload, key)


def lookup(adapter: str | None, key: str) -> str | None:
    finder = _LOOKUPS.get(adapter or "")
    return finder(key) if finder else None
