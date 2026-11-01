"""Effects of approved internal actions. They run only after the trust gate has passed."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from kernel.events import publish
from kernel.trust import AdapterRejected
from packs.talent.events import CandidateHired, StageChanged
from packs.talent.models import Application, Candidate, StageEvent

HIREABLE_STAGES = {"shortlisted", "interview"}


def _move(
    session: Session, tenant_id: UUID, application_id: UUID, stage: str, reason: str | None
) -> None:
    application = session.get(Application, application_id, with_for_update=True)
    if application is None or application.stage == stage:
        return
    previous = application.stage
    application.stage = stage
    session.add(
        StageEvent(
            tenant_id=tenant_id,
            application_id=application.id,
            from_stage=previous,
            to_stage=stage,
            reason=reason,
        )
    )
    publish(
        session,
        tenant_id,
        StageChanged(
            application_id=application.id,
            job_id=application.job_id,
            from_stage=previous,
            to_stage=stage,
        ),
    )


def confirm_shortlist(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    for application_id in payload["application_ids"]:
        _move(session, tenant_id, UUID(application_id), "shortlisted", "Shortlist approved")
    return f"shortlisted:{len(payload['application_ids'])}"


def reject_application(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    _move(session, tenant_id, UUID(payload["application_id"]), "rejected", payload.get("reason"))
    return f"rejected:{payload['application_id']}"


def hire_candidate(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    """Only a shortlisted or interviewed candidate can be hired. Re-checked when it runs."""
    application = session.get(Application, UUID(payload["application_id"]), with_for_update=True)
    if application is None:
        raise AdapterRejected("The application no longer exists")
    if application.stage == "hired":
        return f"already_hired:{application.id}"
    if application.stage not in HIREABLE_STAGES:
        raise AdapterRejected(f"A candidate at the {application.stage} stage cannot be hired")
    candidate = session.get(Candidate, application.candidate_id)
    _move(session, tenant_id, application.id, "hired", payload.get("reason"))
    publish(
        session,
        tenant_id,
        CandidateHired(
            application_id=application.id,
            job_id=application.job_id,
            candidate_id=candidate.id,
            person_id=candidate.person_id,
        ),
    )
    return f"hired:{application.id}"
