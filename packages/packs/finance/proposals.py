"""Shared handling of proposals a person starts, so each action behaves the same way."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel import trust
from kernel.db import utcnow
from kernel.errors import Conflict
from kernel.identity import Actor

OPEN_STATUSES = {"pending_approval", "approved", "executing", "unknown", "blocked"}


def next_attempt(session: Session, actor: Actor, prefix: str, label: str) -> int:
    """A rejected, failed or expired request can be made again. An open one cannot be doubled."""
    earlier = session.scalars(
        select(trust.Proposal)
        .where(trust.Proposal.idempotency_key.startswith(prefix, autoescape=True))
        .order_by(trust.Proposal.created_at)
    ).all()
    for proposal in earlier:
        if proposal.status == "pending_approval" and proposal.expires_at <= utcnow():
            trust.supersede(session, proposal, str(actor.user_id), "Expired before approval")
        elif proposal.status in OPEN_STATUSES:
            raise Conflict(
                f"{label} already has a request that is {proposal.status.replace('_', ' ')}"
            )
    return len(earlier) + 1
