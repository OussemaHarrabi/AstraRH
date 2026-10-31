"""Demo jobs with approved rubrics. Idempotent."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packs.talent.models import Job, Rubric


def seed(session: Session, tenant_id: UUID, world: dict) -> None:
    for spec in world["jobs"]:
        job = session.scalar(select(Job).where(Job.external_id == spec["id"]))
        if job is not None:
            continue
        job = Job(
            tenant_id=tenant_id,
            external_id=spec["id"],
            title=spec["title"],
            description=spec["description"],
            org_unit=spec["org_unit"],
        )
        session.add(job)
        session.flush()
        rubric = Rubric(
            tenant_id=tenant_id,
            job_id=job.id,
            version=1,
            status="active",
            source="human",
            criteria=spec["criteria"],
        )
        session.add(rubric)
        session.flush()
        job.active_rubric_id = rubric.id
