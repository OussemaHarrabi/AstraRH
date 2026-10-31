"""Load the fictional company policies. Idempotent. Run in the worker by `astra.py seed`."""

from pathlib import Path

import yaml
from sqlalchemy import select

from kernel import knowledge
from kernel.db import global_session, tenant_session
from kernel.identity.models import Tenant
from kernel.knowledge.models import Document

ROOT = Path(__file__).resolve().parents[3]
POLICIES = ROOT / "data" / "demo" / "policies"
TENANT_SLUG = "cds"


def main() -> None:
    with global_session() as session:
        tenant_id = session.scalar(select(Tenant.id).where(Tenant.slug == TENANT_SLUG))
    index = yaml.safe_load((POLICIES / "index.yaml").read_text(encoding="utf-8"))
    added = 0
    for item in index:
        with tenant_session(tenant_id) as session:
            exists = session.scalar(select(Document.id).where(Document.external_id == item["id"]))
            if exists:
                continue
            knowledge.ingest_document(
                session,
                tenant_id,
                item["id"],
                item["title"],
                (POLICIES / item["file"]).read_text(encoding="utf-8"),
                item.get("audience_roles"),
                str(item.get("version", "1")),
                item.get("effective_date"),
            )
            added += 1
    print(f"Loaded {added} policy documents.")


if __name__ == "__main__":
    main()
