"""Bank adapter. The sandbox bank stands in for a real provider behind the same interface.

A release is one batch. The batch key is the proposal's idempotency key, so a send can be looked up
and a repeat never pays twice. A bank that definitely refuses raises AdapterRejected. A timeout or
any other failure leaves the outcome unknown, and nothing is ever resent by itself.
"""

import os
from decimal import Decimal
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from kernel.payments import AMOUNT, CURRENCY, MAX_LINES, TOKEN
from kernel.trust import AdapterRejected

BANK_TIMEOUT_SECONDS = 10


def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    return httpx.request(
        method, f"{os.environ['BANK_URL']}{path}", timeout=BANK_TIMEOUT_SECONDS, **kwargs
    )


def build(payload: dict[str, Any], key: str) -> dict[str, Any]:
    """Check the payload and shape the bank request. No network, so it can be tested on its own."""
    lines = payload.get("lines")
    if not isinstance(lines, list) or not lines:
        raise AdapterRejected("A payment release needs at least one line")
    if len(lines) > MAX_LINES:
        raise AdapterRejected(f"A release has at most {MAX_LINES} lines")
    if payload.get("currency") != CURRENCY:
        raise AdapterRejected(f"Only {CURRENCY} payments are supported")
    seen: set[str] = set()
    total = Decimal(0)
    shaped = []
    for line in lines:
        try:
            line_id = str(UUID(str(line["line_id"])))
            token, amount = str(line["token"]), str(line["amount"])
        except (KeyError, ValueError):
            raise AdapterRejected("A payment line is incomplete") from None
        if not TOKEN.match(token):
            raise AdapterRejected("A payment line has an account token that is not allowed")
        if not AMOUNT.match(amount) or Decimal(amount) <= 0:
            raise AdapterRejected("A payment amount must be above zero with three decimals")
        if line_id in seen:
            raise AdapterRejected("A payment line appears twice")
        seen.add(line_id)
        total += Decimal(amount)
        shaped.append({"line_id": line_id, "token": token, "amount": amount})
    if format(total, "f") != str(payload.get("total")):
        raise AdapterRejected("The total does not match the lines")
    if payload.get("count") != len(shaped):
        raise AdapterRejected("The line count does not match the lines")
    return {
        "key": key,
        "tenant_id": str(payload.get("tenant_id")),
        "lines": shaped,
        "total": str(total),
    }


def send(payload: dict[str, Any], key: str) -> str:
    body = build(payload, key)
    response = _request("POST", "/batches", json=body)
    if response.status_code in {409, 422}:
        raise AdapterRejected(f"The bank refused the batch: {response.json().get('detail')}")
    response.raise_for_status()
    return response.json()["reference"]


def find(key: str) -> str | None:
    """Ask the bank whether this batch exists, so a lost reply is never paid twice."""
    response = _request("GET", f"/batches/{quote(key, safe='')}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()["reference"]


def statuses(since: int) -> tuple[int, list[dict[str, Any]]]:
    """Every status the bank has reported after the cursor."""
    response = _request("GET", "/statuses", params={"since": since})
    response.raise_for_status()
    body = response.json()
    return int(body["cursor"]), list(body["statuses"])
