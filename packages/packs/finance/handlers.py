"""Effects of approved internal actions. They run only after the trust gate has passed."""

from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from kernel.db import utcnow
from kernel.errors import KernelError
from kernel.trust import AdapterRejected, Approval, Proposal
from packs.finance import service
from packs.finance.models import RuleSetRecord


def _approver(session: Session, key: str) -> UUID | None:
    return session.scalar(
        select(Approval.approver_id)
        .join(Proposal, Proposal.id == Approval.proposal_id)
        .where(
            Proposal.idempotency_key == key,
            Approval.status == "active",
            Approval.decision == "approved",
        )
        .order_by(Approval.created_at.desc())
        .limit(1)
    )


def activate_rule_set(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    """Re-checks everything when it runs, so a change after approval cannot slip in."""
    record = session.get(RuleSetRecord, UUID(payload["rule_set_id"]), with_for_update=True)
    if record is None:
        raise AdapterRejected("The rule set no longer exists")
    if record.definition_hash != payload["definition_hash"]:
        raise AdapterRejected("The rule set changed after it was approved")
    # One activation at a time per tenant, so two cannot both pass the overlap check.
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"finance.rules.activate:{tenant_id}"},
    )
    try:
        service.check_activatable(session, record)
    except KernelError as exc:
        raise AdapterRejected(exc.message) from exc
    record.status = "active"
    record.approved_by = _approver(session, key)
    record.approved_at = utcnow()
    return f"rule_set:{record.rule_id}:active"
