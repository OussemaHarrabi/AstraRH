"""Event consumers. The worker must import this module to register them (kernel request K7)."""

from uuid import UUID

from sqlalchemy.orm import Session

from kernel.events import EventOutbox, subscribe
from packs.finance import engagements

HIRED = "hired"


@subscribe("talent.application.stage_changed.v1", "finance.record_hire")
def record_hire(session: Session, event: EventOutbox) -> None:
    """A candidate reached 'hired'. The event carries no employee or terms, so HR completes a
    notice. Nothing in talent moves a candidate to 'hired' yet (kernel request K1)."""
    if event.payload["to_stage"] != HIRED:
        return
    engagements.record_hire(
        session,
        event.tenant_id,
        UUID(event.payload["application_id"]),
        UUID(event.payload["job_id"]),
        str(event.id),
    )
