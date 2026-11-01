"""Effects of approved internal actions. They run only after the trust gate has passed."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from kernel.db import utcnow
from kernel.errors import KernelError
from kernel.events import publish
from kernel.trust import AdapterRejected, Approval, Proposal
from packs.finance import engagements, issues, runs, service
from packs.finance.events import EngagementActivated, PayrollApproved
from packs.finance.models import Engagement, PayrollRun, Payslip, RuleSetRecord


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


def _proposal(session: Session, key: str) -> Proposal:
    proposal = session.scalar(select(Proposal).where(Proposal.idempotency_key == key))
    if proposal is None:
        raise AdapterRejected("The proposal behind this action cannot be found")
    return proposal


def activate_engagement(
    session: Session, tenant_id: UUID, payload: dict[str, Any], key: str
) -> str:
    """Re-validates and re-hashes the terms when it runs, so an edit after approval is refused."""
    row = session.get(Engagement, UUID(payload["engagement_id"]), with_for_update=True)
    if row is None:
        raise AdapterRejected("The engagement no longer exists")
    if row.status != "approved":
        raise AdapterRejected(f"The engagement is {row.status}, not approved")
    if engagements.terms_hash(session, row) != payload["terms_hash"]:
        raise AdapterRejected("The terms changed after they were approved")
    engagements.validate_engagement(session, tenant_id, row)
    if row.status != "approved":
        raise AdapterRejected("The engagement no longer passes validation")
    row.status = "active"
    row.activated_by = _approver(session, key)
    row.activated_at = utcnow()
    publish(
        session,
        tenant_id,
        EngagementActivated(
            engagement_id=row.id,
            employee_id=row.employee_id,
            type=row.type,
            starts_on=row.starts_on,
        ),
    )
    return f"engagement:{row.id}:active"


def amend_engagement(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    proposal = _proposal(session, key)
    try:
        amendment = engagements.apply_amendment(
            session, tenant_id, payload, proposal.requested_by, proposal.id
        )
    except KernelError as exc:
        raise AdapterRejected(exc.message) from exc
    return f"amendment:{amendment.id}"


def approve_run(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    """Re-checks everything when it runs: the results, every payslip's replay, the open issues
    and who is approving."""
    run = session.get(PayrollRun, UUID(payload["run_id"]), with_for_update=True)
    if run is None:
        raise AdapterRejected("The payroll run no longer exists")
    if run.status != "approval_pending":
        raise AdapterRejected(f"The run is {run.status}, not waiting for approval")
    if run.results_hash != payload["results_hash"]:
        raise AdapterRejected("The results changed after they were submitted")
    if runs.results_hash_of(session, run.id) != run.results_hash:
        raise AdapterRejected("The payslips no longer match the calculated results")
    open_now = issues.open_for(session, runs.ENTITY, run.id)
    if any(i.severity in {"blocking", "review"} for i in open_now):
        raise AdapterRejected("The run still has open issues")
    approver = _approver(session, key)
    if approver is not None and approver == run.prepared_by:
        raise AdapterRejected("The person who prepared the run cannot approve it")
    if not runs.verify_run(session, run.id)["verified"]:
        raise AdapterRejected("A payslip does not replay to the figures that were recorded")
    run.status = "approved"
    run.approved_by = approver
    run.approved_at = utcnow()
    session.execute(update(Payslip).where(Payslip.run_id == run.id).values(status="approved"))
    count = session.scalar(
        select(func.count()).select_from(Payslip).where(Payslip.run_id == run.id)
    )
    publish(session, tenant_id, PayrollApproved(run_id=run.id, payslips=count))
    return f"run:{run.id}:approved"
