"""AstraRH sandbox bank: a deterministic stand-in for a real payment provider.

Only the executor can reach it, on its own network. It is not a bank: it keeps its state in memory
(a restart clears it), accepts batches, and reports statuses that the account token decides, so a
demo and the tests are repeatable:

    ACC-...-FAIL      the line fails (ACCOUNT_CLOSED)
    ACC-...-PART      the line is part paid (half the amount, rounded down)
    ACC-...-REV       the line is paid and later reversed
    ACC-...-MISMATCH  the line is reported paid with a different amount
    ACC-...-REFUSE    the whole batch is refused
    anything else     the line is paid
"""

import threading
from decimal import ROUND_DOWN, Decimal
from hashlib import sha256
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from kernel.payments import AMOUNT, TOKEN

app = FastAPI(title="AstraRH sandbox bank", docs_url=None, redoc_url=None, openapi_url=None)

_lock = threading.Lock()
_batches: dict[str, dict[str, Any]] = {}
_statuses: list[dict[str, Any]] = []
MILLIME = Decimal("0.001")


class Line(BaseModel):
    line_id: str
    token: str
    amount: str


class Batch(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    tenant_id: str
    lines: list[Line] = Field(min_length=1, max_length=5000)
    total: str


def _outcomes(line: Line) -> list[tuple[str, Decimal, str | None]]:
    amount = Decimal(line.amount)
    token = line.token
    if token.endswith("-FAIL"):
        return [("failed", Decimal(0), "ACCOUNT_CLOSED")]
    if token.endswith("-PART"):
        return [("part_paid", (amount / 2).quantize(MILLIME, rounding=ROUND_DOWN), None)]
    if token.endswith("-REV"):
        return [("paid", amount, None), ("reversed", amount, "RETURNED_BY_BANK")]
    if token.endswith("-MISMATCH"):
        return [("paid", amount - Decimal(1), None)]
    return [("paid", amount, None)]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/batches", status_code=201)
def create_batch(batch: Batch, response: Response) -> dict[str, str]:
    for line in batch.lines:
        if not TOKEN.match(line.token) or not AMOUNT.match(line.amount):
            raise HTTPException(422, "A line has an account or an amount the bank does not accept")
        if line.token.endswith("-REFUSE"):
            raise HTTPException(422, "The account refused the payment")
    if sum((Decimal(line.amount) for line in batch.lines), Decimal(0)) != Decimal(batch.total):
        raise HTTPException(422, "The total does not match the lines")
    fingerprint = sha256(batch.model_dump_json().encode()).hexdigest()
    with _lock:
        existing = _batches.get(batch.key)
        if existing is not None:
            if existing["fingerprint"] != fingerprint:
                raise HTTPException(409, "This key was used for a different batch")
            response.status_code = 200
            return {"reference": existing["reference"]}
        reference = f"BANK-{sha256(batch.key.encode()).hexdigest()[:12].upper()}"
        _batches[batch.key] = {"reference": reference, "fingerprint": fingerprint}
        for line in batch.lines:
            for sequence, (status, paid, reason) in enumerate(_outcomes(line), start=1):
                _statuses.append(
                    {
                        "cursor": len(_statuses) + 1,
                        "reference": reference,
                        "key": batch.key,
                        "tenant_id": batch.tenant_id,
                        "line_id": line.line_id,
                        "status": status,
                        "seq": sequence,
                        "paid_amount": format(paid.quantize(Decimal("0.001")), "f"),
                        "reason": reason,
                    }
                )
    return {"reference": reference}


@app.get("/batches/{key:path}")
def get_batch(key: str) -> dict[str, str]:
    with _lock:
        found = _batches.get(key)
    if found is None:
        raise HTTPException(404, "No such batch")
    return {"reference": found["reference"]}


@app.get("/statuses")
def list_statuses(since: int = 0) -> dict[str, Any]:
    with _lock:
        fresh = [s for s in _statuses if s["cursor"] > since]
        cursor = _statuses[-1]["cursor"] if _statuses else since
    return {"cursor": cursor, "statuses": fresh}
