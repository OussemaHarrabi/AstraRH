"""Effects of approved internal actions. They run only after the trust gate has passed."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from kernel.events import publish
from packs.talent.events import StageChanged
from packs.talent.models import Application, StageEvent


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
