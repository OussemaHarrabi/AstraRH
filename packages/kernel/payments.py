"""Bank payment contracts shared by the executor's adapter and the packs that consume the result.

Only these opaque things cross the boundary: an account token, an amount and a status. Account
numbers never appear in AstraRH. The model sits here, not in the adapters package, because only the
executor may import adapters, while packs read the events.
"""

import re

from pydantic import BaseModel

from kernel.events import event_type

CURRENCY = "TND"
TOKEN = re.compile(r"^ACC-[A-Z0-9-]{4,40}$")
AMOUNT = re.compile(r"^\d{1,12}\.\d{3}$")
LINE_STATUSES = {"paid", "part_paid", "failed", "reversed"}
MAX_LINES = 5000


@event_type("bank.payment.status_reported.v1")
class PaymentStatusReported(BaseModel):
    """What the bank said about one payment line. The amounts were compared by the executor, which
    holds the approved payload, so the event says only whether they matched."""

    provider_ref: str
    key: str
    line_id: str
    status: str
    status_seq: int
    amount_matches: bool
    reason_code: str | None = None
