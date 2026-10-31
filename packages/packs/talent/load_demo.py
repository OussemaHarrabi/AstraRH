"""Upload the demo CVs for the backend job through the normal pipeline. Skips files already in."""

import json
from pathlib import Path

from sqlalchemy import select

from kernel.db import global_session, tenant_session
from kernel.errors import Conflict
from kernel.identity.models import Tenant
from packs.talent import service
from packs.talent.models import Job

ROOT = Path(__file__).resolve().parents[3]
CVS = ROOT / "data" / "demo" / "cvs"
TENANT_SLUG = "cds"
DEMO_JOB = "JOB-BE-01"


def main() -> None:
    labels = json.loads((ROOT / "data" / "demo" / "labels.json").read_text(encoding="utf-8"))
    with global_session() as session:
        tenant_id = session.scalar(select(Tenant.id).where(Tenant.slug == TENANT_SLUG))
    with tenant_session(tenant_id) as session:
        job_id = session.scalar(select(Job.id).where(Job.external_id == DEMO_JOB))
    added = 0
    for filename in sorted(labels):
        try:
            with tenant_session(tenant_id) as session:
                service.add_cv(session, tenant_id, job_id, filename, (CVS / filename).read_bytes())
                added += 1
        except Conflict:
            continue
    print(f"Queued {added} CVs for {DEMO_JOB}. The worker is reading them now.")


if __name__ == "__main__":
    main()
