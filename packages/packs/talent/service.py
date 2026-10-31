"""Talent operations shared by the HTTP API, the demo loader and the tests."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel import files
from kernel.errors import Conflict, NotFound, ValidationFailed
from kernel.events import publish
from kernel.ids import uuid7
from kernel.people.models import Person
from packs.talent.events import CvUploaded, JobCreated, RankingRequested
from packs.talent.models import (
    Application,
    Candidate,
    CvDocument,
    Job,
    RankingRun,
    Rubric,
)


def create_job(
    session: Session,
    tenant_id: UUID,
    title: str,
    description: str,
    org_unit: str | None = None,
) -> Job:
    job = Job(
        tenant_id=tenant_id,
        external_id=f"JOB-{uuid7().hex}",
        title=title,
        description=description,
        org_unit=org_unit,
    )
    session.add(job)
    session.flush()
    publish(session, tenant_id, JobCreated(job_id=job.id))
    return job


def validate_criteria(criteria: list[dict[str, Any]]) -> None:
    if not criteria:
        raise ValidationFailed("A rubric needs at least one criterion")
    ids = [c["id"] for c in criteria]
    if len(ids) != len(set(ids)):
        raise ValidationFailed("Criterion ids must be unique")
    total = sum((Decimal(str(c["weight"])) for c in criteria), Decimal(0))
    if total != Decimal(1):
        raise ValidationFailed(f"Weights must sum to exactly 1, not {total}")
    if any(Decimal(str(c["weight"])) <= 0 for c in criteria):
        raise ValidationFailed("Every weight must be above 0")


def save_rubric(
    session: Session, tenant_id: UUID, job_id: UUID, criteria: list[dict[str, Any]]
) -> Rubric:
    """Each edit is a new draft version. Versions that produced scores are never changed."""
    validate_criteria(criteria)
    latest = session.scalar(
        select(Rubric).where(Rubric.job_id == job_id).order_by(Rubric.version.desc()).limit(1)
    )
    rubric = Rubric(
        tenant_id=tenant_id,
        job_id=job_id,
        version=(latest.version + 1) if latest else 1,
        status="draft",
        source="human",
        criteria=criteria,
    )
    session.add(rubric)
    session.flush()
    return rubric


def activate_rubric(session: Session, job: Job, rubric: Rubric, actor_id: UUID) -> None:
    validate_criteria(rubric.criteria)
    rubric.status = "active"
    rubric.approved_by = actor_id
    job.active_rubric_id = rubric.id


def add_cv(
    session: Session, tenant_id: UUID, job_id: UUID, filename: str, data: bytes
) -> CvDocument:
    """Passes the upload gate, stores the file, and opens an application. Reading happens later."""
    stored = files.put(tenant_id, filename, data)
    duplicate = session.scalar(
        select(CvDocument.id).where(CvDocument.job_id == job_id, CvDocument.sha256 == stored.sha256)
    )
    if duplicate:
        raise Conflict(f"{filename}: this exact file was already uploaded for this job")
    person = Person(tenant_id=tenant_id, external_id=f"CAND-{uuid7().hex}", lifecycle="candidate")
    session.add(person)
    session.flush()
    candidate = Candidate(tenant_id=tenant_id, person_id=person.id)
    session.add(candidate)
    session.flush()
    application = Application(tenant_id=tenant_id, job_id=job_id, candidate_id=candidate.id)
    session.add(application)
    session.flush()
    cv = CvDocument(
        tenant_id=tenant_id,
        application_id=application.id,
        job_id=job_id,
        filename=filename,
        file_key=stored.key,
        sha256=stored.sha256,
    )
    session.add(cv)
    session.flush()
    publish(
        session,
        tenant_id,
        CvUploaded(cv_id=cv.id, job_id=job_id, application_id=application.id),
    )
    return cv


def request_ranking(
    session: Session, tenant_id: UUID, job_id: UUID, requested_by: UUID | None = None
) -> RankingRun:
    job = session.get(Job, job_id)
    if job is None:
        raise NotFound("Job not found")
    if job.active_rubric_id is None:
        raise ValidationFailed("Approve the screening criteria before ranking")
    running = session.scalar(
        select(RankingRun.id).where(
            RankingRun.job_id == job_id, RankingRun.status.in_(["requested", "running"])
        )
    )
    if running:
        raise Conflict("A ranking is already running for this job")
    ready = session.scalar(
        select(CvDocument.id)
        .where(CvDocument.job_id == job_id, CvDocument.status == "ready")
        .limit(1)
    )
    if ready is None:
        raise ValidationFailed("No CV is ready to rank yet")
    ranking = RankingRun(
        tenant_id=tenant_id,
        job_id=job_id,
        rubric_id=job.active_rubric_id,
        requested_by=requested_by,
    )
    session.add(ranking)
    session.flush()
    publish(session, tenant_id, RankingRequested(ranking_id=ranking.id, job_id=job_id))
    return ranking
