"""Event consumers. The worker imports this module to register them (apps/worker/main.py)."""

from uuid import UUID

from sqlalchemy.orm import Session

from kernel.events import EventOutbox, subscribe
from packs.finance import engagements


@subscribe("talent.candidate.hired.v1", "finance.record_hire")
def record_hire(session: Session, event: EventOutbox) -> None:
    """A candidate was hired. The event has IDs only, no employee or terms, so HR completes a
    notice with the real employee and the pay."""
    payload = event.payload
    engagements.record_hire(
        session,
        event.tenant_id,
        UUID(payload["application_id"]),
        UUID(payload["job_id"]),
        UUID(payload["candidate_id"]),
        UUID(payload["person_id"]),
        str(event.id),
    )
