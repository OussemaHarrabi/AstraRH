"""Event consumers. The worker imports this module to register them (apps/worker/main.py)."""

from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from kernel.events import EventOutbox, subscribe
from packs.finance import engagements, inputs, payments, runs


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


@subscribe("finance.payroll.calculation_requested.v1", "finance.calculate_run")
def calculate_run(session: Session, event: EventOutbox) -> None:
    """Only the worker may write payslips, so calculation starts from this event."""
    runs.calculate(session, event.tenant_id, UUID(event.payload["run_id"]))


@subscribe("trust.proposal.rejected.v1", "finance.reopen_rejected_run")
def reopen_rejected_run(session: Session, event: EventOutbox) -> None:
    """The approver said no, so the run goes back to draft."""
    if event.payload["action_type"] == runs.APPROVE_ACTION:
        runs.mark_rejected(session, event.tenant_id, UUID(event.payload["proposal_id"]))


@subscribe("trust.action.executed.v1", "finance.record_payment_release")
def record_payment_release(session: Session, event: EventOutbox) -> None:
    """The executor sent a release. Only its result reaches finance, as this event."""
    if event.payload["action_type"] == payments.RELEASE_ACTION:
        payments.record_release(
            session,
            event.tenant_id,
            UUID(event.payload["proposal_id"]),
            UUID(event.payload["execution_id"]),
        )


@subscribe("bank.payment.status_reported.v1", "finance.apply_payment_status")
def apply_payment_status(session: Session, event: EventOutbox) -> None:
    """What the bank said about one payment, published by the executor."""
    payments.apply_status(session, event.tenant_id, event.payload)


def _approved_input(session: Session, event: EventOutbox, kind: str) -> None:
    payload = event.payload
    employee = str(payload["employee"])
    effective = date.fromisoformat(payload["effective_date"])
    row = inputs.RawRow(
        1,
        {
            "employee": employee,
            "kind": kind,
            "effective_date": effective.isoformat(),
            "quantity": str(payload.get("quantity", "")),
            "amount": str(payload.get("amount", "")),
            "reference": str(payload.get("reference", event.id)),
        },
    )
    inputs.import_rows(
        session,
        event.tenant_id,
        UUID(str(payload.get("submitted_by", event.id))),
        "workforce",
        effective,
        effective,
        [row],
        f"event:{event.id}",
    )


@subscribe("workforce.leave.approved.v1", "finance.import_leave")
def import_leave(session: Session, event: EventOutbox) -> None:
    _approved_input(session, event, "absence")


@subscribe("workforce.time.approved.v1", "finance.import_time")
def import_time(session: Session, event: EventOutbox) -> None:
    _approved_input(session, event, "hours")
