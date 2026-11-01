"""Mailbox pull. Only the executor imports it: the one process that may talk to the provider.

It copies raw messages addressed to a tenant's HR mailbox into `comms.inbound_mail` and nothing
else. Its database role can insert there and read the provider ids back, never the content, so a
compromised executor still can't read the inbox. Parsing happens later in the worker.
Mailpit's HTTP API stands in for a real provider (IMAP, Microsoft Graph, Gmail).
"""

import logging
import os
from uuid import UUID

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from kernel.comms.models import InboundMail
from kernel.db import global_session, tenant_session, utcnow

DEFAULT_MAILBOXES = "cds=hr@cds.example.test"
PAGE_SIZE = 50
MAX_RAW_BYTES = 25 * 1024 * 1024
TIMEOUT_SECONDS = 10

log = logging.getLogger("astra.mailbox")


def mailboxes() -> dict[str, str]:
    """`slug=address` pairs, comma separated, from INBOUND_MAILBOXES."""
    pairs = os.environ.get("INBOUND_MAILBOXES", DEFAULT_MAILBOXES)
    result = {}
    for pair in filter(None, (item.strip() for item in pairs.split(","))):
        slug, _, address = pair.partition("=")
        if slug and "@" in address:
            result[slug.strip()] = address.strip().lower()
    return result


def _api() -> str:
    return f"http://{os.environ['SMTP_HOST']}:8025/api/v1"


def _tenant_id(slug: str) -> UUID | None:
    with global_session() as session:
        return session.scalar(
            text("SELECT id FROM core.tenant WHERE slug = :slug AND active"), {"slug": slug}
        )


def poll(tenant_id: UUID, address: str) -> int:
    """Copy new messages for one mailbox. Returns how many were stored."""
    listing = httpx.get(
        f"{_api()}/search",
        params={"query": f'to:"{address}"', "limit": PAGE_SIZE},
        timeout=TIMEOUT_SECONDS,
    )
    listing.raise_for_status()
    found = {
        f"mailpit:{item.get('MessageID') or item['ID']}": item
        for item in listing.json().get("messages", [])
    }
    if not found:
        return 0
    with tenant_session(tenant_id) as session:
        known = set(
            session.scalars(
                select(InboundMail.provider_id).where(InboundMail.provider_id.in_(found))
            )
        )
    stored = 0
    for provider_id, item in found.items():
        if provider_id in known:
            continue
        row = {
            "tenant_id": tenant_id,
            "provider_id": provider_id,
            "mailbox": address,
            "received_at": utcnow(),
            "size": int(item.get("Size") or 0),
        }
        if row["size"] > MAX_RAW_BYTES:
            row |= {"status": "rejected", "reason": "Larger than 25 MB"}
        else:
            raw = httpx.get(f"{_api()}/message/{item['ID']}/raw", timeout=TIMEOUT_SECONDS)
            raw.raise_for_status()
            row |= {"raw": raw.content, "size": len(raw.content), "status": "pending"}
        # No RETURNING: this role may not read rows back.
        with tenant_session(tenant_id) as session:
            session.execute(insert(InboundMail).values(**row).on_conflict_do_nothing())
        stored += 1
    return stored


def poll_all() -> int:
    stored = 0
    for slug, address in mailboxes().items():
        tenant_id = _tenant_id(slug)
        if tenant_id is None:
            continue
        try:
            stored += poll(tenant_id, address)
        except httpx.HTTPError:
            log.warning("Mailbox %s unreachable", address)
    return stored
