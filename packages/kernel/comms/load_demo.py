"""Load the fictional emails. Idempotent. Run in the worker by `astra.py seed`."""

import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from kernel import comms
from kernel.db import global_session, tenant_session, utcnow
from kernel.identity.models import Tenant

ROOT = Path(__file__).resolve().parents[3]
EMAILS = ROOT / "data" / "demo" / "emails.json"
TENANT_SLUG = "cds"
HR_ADDRESS = "recrutement@cds.example.test"


def main() -> None:
    emails = json.loads(EMAILS.read_text(encoding="utf-8"))
    with global_session() as session:
        tenant_id = session.scalar(select(Tenant.id).where(Tenant.slug == TENANT_SLUG))
    added = 0
    for email in emails:
        inbound = email.get("direction", "in") == "in"
        with tenant_session(tenant_id) as session:
            stored = comms.ingest(
                session,
                tenant_id,
                f"demo:{email['id']}",
                email.get("direction", "in"),
                email["from"] if inbound else HR_ADDRESS,
                HR_ADDRESS if inbound else email["to"],
                email["subject"],
                email["body"],
                utcnow() - timedelta(hours=email.get("hours_ago", 1)),
            )
            added += 1 if stored else 0
    print(f"Queued {added} emails. The worker is sorting them now.")


if __name__ == "__main__":
    main()
