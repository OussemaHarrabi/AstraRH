"""Payments: destinations, release, what the bank reported, and closing a run.

Only the executor reaches the bank. This module runs in the API, which reads and proposes, and
in the worker, which records what happened. The executor never touches finance tables: its
result arrives as events.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kernel import explain, trust
from kernel.db import utcnow
from kernel.errors import Conflict, NotFound, ValidationFailed
from kernel.events import publish
from kernel.identity import Actor
from kernel.payments import CURRENCY, LINE_STATUSES, TOKEN
from kernel.people.models import Employee
from kernel.trust.models import Execution, Proposal
from packs.finance import issues, proposals, runs
from packs.finance.events import PaymentReconciled, PaymentSubmitted, PayrollClosed
from packs.finance.models import (
    PaymentBatch,
    PaymentDestination,
    PaymentLine,
    PaymentStatusEvent,
    PayrollRun,
    Payslip,
)
from packs.finance.validation.common import BLOCKING, IssueSpec

RELEASE_ACTION = "finance.payment.release"
CLOSE_ACTION = "finance.payroll.close"
ENTITY = "payroll_payment"
RELEASABLE = {"due", "failed", "reversed"}
TRANSITIONS = {
    ("submitted", "paid"),
    ("submitted", "part_paid"),
    ("submitted", "failed"),
    ("submitted", "reversed"),
    ("paid", "reversed"),
    ("part_paid", "paid"),
}
DECISION_VIEW_ROLES = ["admin", "finance", "auditor"]
SANDBOX_NOTICE = (
    "This pays through the sandbox bank, not a real provider. Nothing leaves the system and no "
    "money moves."
)


class MissingDestination(Exception):
    def __init__(self, employees: list[str]) -> None:
        super().__init__(", ".join(employees))
        self.employees = employees


def _text(value: Decimal) -> str:
    return format(value, "f")


def mask(token: str) -> str:
    return f"ACC-...{token[-4:]}"


def set_destination(
    session: Session, tenant_id: UUID, actor: Actor, employee_id: UUID, token: str
) -> PaymentDestination:
    """Records an opaque account token. An account number is never stored."""
    if not TOKEN.match(token):
        raise ValidationFailed("A token looks like ACC- followed by letters, digits and dashes")
    if session.get(Employee, employee_id) is None:
        raise NotFound("Employee not found")
    row = session.scalar(
        select(PaymentDestination).where(PaymentDestination.employee_id == employee_id)
    )
    if row is None:
        row = PaymentDestination(
            tenant_id=tenant_id, employee_id=employee_id, token=token, set_by=actor.user_id
        )
        session.add(row)
    else:
        row.token, row.set_by, row.updated_at = token, actor.user_id, utcnow()
    session.flush()
    return row


def destinations_of(session: Session, employee_ids: list[UUID]) -> dict[UUID, str]:
    rows = session.scalars(
        select(PaymentDestination).where(PaymentDestination.employee_id.in_(employee_ids))
    )
    return {row.employee_id: row.token for row in rows}


def create_lines(session: Session, tenant_id: UUID, run: PayrollRun) -> int:
    """Worker only. One line per payslip with net pay, created when the run is approved."""
    slips = list(session.scalars(select(Payslip).where(Payslip.run_id == run.id)))
    have = set(session.scalars(select(PaymentLine.payslip_id).where(PaymentLine.run_id == run.id)))
    tokens = destinations_of(session, [s.employee_id for s in slips])
    missing = [
        session.get(Employee, s.employee_id).external_id
        for s in slips
        if s.net_pay > 0 and s.employee_id not in tokens
    ]
    if missing:
        raise MissingDestination(missing)
    created = 0
    for slip in slips:
        if slip.net_pay <= 0 or slip.id in have:
            continue
        session.add(
            PaymentLine(
                tenant_id=tenant_id,
                run_id=run.id,
                payslip_id=slip.id,
                amount=slip.net_pay,
                bank_ref_token=tokens[slip.employee_id],
                idempotency_key=f"pay:{slip.id}",
            )
        )
        created += 1
    session.flush()
    return created


def _lines(session: Session, run_id: UUID) -> list[PaymentLine]:
    return list(
        session.scalars(
            select(PaymentLine).where(PaymentLine.run_id == run_id).order_by(PaymentLine.id)
        )
    )


def request_release(
    session: Session, tenant_id: UUID, actor: Actor, run_id: UUID
) -> trust.Proposal:
    """Propose paying every line that is due, failed or reversed (R3). Nothing is sent until a
    second person approves, and the executor is the only one that sends."""
    run = session.get(PayrollRun, run_id, with_for_update=True)
    if run is None:
        raise NotFound("Payroll run not found")
    if run.status not in {"approved", "payment_pending"}:
        raise Conflict(f"The run is {run.status.replace('_', ' ')}, so nothing can be released")
    if runs.results_hash_of(session, run.id) != run.results_hash:
        raise Conflict("The payslips no longer match the approved results")
    due = [line for line in _lines(session, run.id) if line.status in RELEASABLE]
    if not due:
        raise Conflict("No payment is due for this run")
    attempt = proposals.next_attempt(
        session, actor, f"{RELEASE_ACTION}:{run.id}:", f"The payments of run {run.id}"
    )
    total = sum((line.amount for line in due), Decimal(0))
    owner = dict(
        session.execute(
            select(Payslip.id, Payslip.employee_id).where(Payslip.run_id == run.id)
        ).all()
    )
    current = destinations_of(session, list(owner.values()))
    payload = {
        "run_id": str(run.id),
        "tenant_id": str(tenant_id),
        "release_number": attempt,
        "currency": CURRENCY,
        "lines": [
            {
                "line_id": str(line.id),
                "token": current.get(owner[line.payslip_id], line.bank_ref_token),
                "amount": _text(line.amount),
                "key": line.idempotency_key,
            }
            for line in due
        ],
        "total": _text(total),
        "count": len(due),
        "results_hash": run.results_hash,
    }
    decision = explain.record(
        session,
        tenant_id,
        explain.DecisionDraft(
            kind="finance.payment.release",
            question=f"Should release {attempt} of this payroll run be paid?",
            outcome={"payments": str(len(due)), "total": _text(total)},
            rationale=(
                f"Release {attempt} of the run for {run.period_start.isoformat()} to "
                f"{run.period_end.isoformat()}: {len(due)} payments totalling {_text(total)} "
                f"{CURRENCY}, from approved payslips."
            ),
            limits=[SANDBOX_NOTICE, "Account details are never shown here, only opaque tokens."],
            versions={"results_hash": run.results_hash},
            view_roles=DECISION_VIEW_ROLES,
        ),
    )
    return trust.propose(
        session,
        tenant_id,
        RELEASE_ACTION,
        payload,
        f"Pay {len(due)} employees from the payroll run ({_text(total)} {CURRENCY})",
        decision.id,
        f"{RELEASE_ACTION}:{run.id}:{attempt}",
        target={"payroll_run_id": str(run.id)},
        requested_by=actor.user_id,
    )


def record_release(
    session: Session, tenant_id: UUID, proposal_id: UUID, execution_id: UUID
) -> PaymentBatch | None:
    """Worker only. The executor sent the batch: remember it and mark its lines submitted."""
    if session.scalar(select(PaymentBatch.id).where(PaymentBatch.execution_id == execution_id)):
        return None
    proposal = session.get(Proposal, proposal_id)
    execution = session.get(Execution, execution_id)
    payload = proposal.payload
    run = session.get(PayrollRun, UUID(payload["run_id"]), with_for_update=True)
    batch = PaymentBatch(
        tenant_id=tenant_id,
        run_id=run.id,
        release_number=int(payload["release_number"]),
        execution_id=execution_id,
        provider_ref=execution.provider_ref,
        total=Decimal(payload["total"]),
        line_count=int(payload["count"]),
    )
    session.add(batch)
    session.flush()
    for item in payload["lines"]:
        line = session.get(PaymentLine, UUID(item["line_id"]), with_for_update=True)
        if line is not None and line.status in RELEASABLE:
            line.bank_ref_token = item["token"]
            line.status = "submitted"
            line.batch_id = batch.id
            line.last_status_seq = 0
            line.failure_reason = None
    if run.status == "approved":
        run.status = "payment_pending"
    session.flush()
    publish(
        session,
        tenant_id,
        PaymentSubmitted(
            run_id=run.id, release_number=batch.release_number, lines=batch.line_count
        ),
    )
    evaluate(session, tenant_id, run)
    return batch


def apply_status(session: Session, tenant_id: UUID, payload: dict[str, Any]) -> None:
    """Worker only. Record what the bank reported, once, and apply it only when it is newer than
    what the line already shows. Never mark a payment paid when the amount did not match."""
    status = payload["status"]
    if status not in LINE_STATUSES:
        raise ValueError(f"Unknown payment status {status!r}")
    line = session.get(PaymentLine, UUID(payload["line_id"]), with_for_update=True)
    if line is None:
        raise LookupError("The bank reported a payment line that does not exist")
    if line.batch_id is None:
        raise RuntimeError("The release is not recorded yet. The bus retries")
    batch = session.get(PaymentBatch, line.batch_id)
    if batch.provider_ref != payload["provider_ref"]:
        return
    sequence = int(payload["status_seq"])
    try:
        with session.begin_nested():
            session.add(
                PaymentStatusEvent(
                    tenant_id=tenant_id,
                    payment_line_id=line.id,
                    provider_ref=payload["provider_ref"],
                    status=status,
                    status_seq=sequence,
                    amount_matches=bool(payload["amount_matches"]),
                    reason_code=payload.get("reason_code"),
                    observed_at=utcnow(),
                )
            )
            session.flush()
    except IntegrityError:
        return
    if sequence <= line.last_status_seq:
        return  # Late and older than what the line already shows: kept as history only
    line.last_status_seq = sequence
    if not payload["amount_matches"]:
        line.failure_reason = "AMOUNT_MISMATCH"
    elif (line.status, status) in TRANSITIONS:
        line.status = status
        line.failure_reason = payload.get("reason_code") if status != "paid" else None
    session.flush()
    run = session.get(PayrollRun, line.run_id, with_for_update=True)
    evaluate(session, tenant_id, run)


def _problems(session: Session, run: PayrollRun) -> list[IssueSpec]:
    externals = dict(
        session.execute(
            select(Payslip.id, Employee.external_id)
            .join(Employee, Employee.id == Payslip.employee_id)
            .where(Payslip.run_id == run.id)
        ).all()
    )
    specs: list[IssueSpec] = []
    for line in _lines(session, run.id):
        who = externals.get(line.payslip_id, "an employee")
        field = f"line:{line.id}"
        reason = line.failure_reason or "no reason given"
        if line.status == "failed":
            code, message, action = (
                "PAYMENT_FAILED",
                f"The payment to {who} failed ({reason}).",
                "Fix the destination and release it again",
            )
        elif line.status == "part_paid":
            code, message, action = (
                "PAYMENT_PART_PAID",
                f"The payment to {who} was only partly paid.",
                "Settle the remainder with the bank",
            )
        elif line.status == "reversed":
            code, message, action = (
                "PAYMENT_REVERSED",
                f"The payment to {who} was returned by the bank ({reason}).",
                "Release it again once the destination is confirmed",
            )
        elif line.status == "submitted" and line.failure_reason == "AMOUNT_MISMATCH":
            code, message, action = (
                "PAYMENT_AMOUNT_MISMATCH",
                f"The bank reports a different amount paid to {who} than was approved.",
                "Check with the bank before anything else is paid",
            )
        else:
            continue
        specs.append(IssueSpec(code, BLOCKING, field, message, action, "FINANCE"))
    return specs


def evaluate(session: Session, tenant_id: UUID, run: PayrollRun) -> None:
    """Recompute the payment problems and move the run to paid when every line is paid."""
    issues.sync(session, tenant_id, ENTITY, run.id, _problems(session, run))
    lines = _lines(session, run.id)
    paid = sum(1 for line in lines if line.status == "paid")
    if lines and paid == len(lines) and run.status == "payment_pending":
        run.status = "paid"
        session.execute(update(Payslip).where(Payslip.run_id == run.id).values(status="paid"))
    elif paid < len(lines) and run.status == "paid":
        # A payment was reversed after the run counted as paid, so it is open again.
        run.status = "payment_pending"
        session.execute(update(Payslip).where(Payslip.run_id == run.id).values(status="approved"))
    session.flush()
    publish(
        session,
        tenant_id,
        PaymentReconciled(
            run_id=run.id,
            paid=paid,
            failed=sum(1 for line in lines if line.status in {"failed", "part_paid", "reversed"}),
        ),
    )


def release_state(session: Session, run: PayrollRun) -> dict[str, Any]:
    """What happened to the latest release request. A failed or unknown send produces no event,
    so it is read from the request itself."""
    latest = session.scalar(
        select(Proposal)
        .where(Proposal.idempotency_key.startswith(f"{RELEASE_ACTION}:{run.id}:", autoescape=True))
        .order_by(Proposal.created_at.desc())
        .limit(1)
    )
    if latest is None:
        return {"state": "none", "release_number": None, "error": None}
    error = session.scalar(select(Execution.error).where(Execution.proposal_id == latest.id))
    state = {"executed": "sent", "pending_approval": "waiting for approval"}.get(
        latest.status, latest.status
    )
    return {
        "state": state,
        "release_number": int(latest.payload["release_number"]),
        "error": error,
    }


def payments_json(session: Session, run: PayrollRun) -> dict[str, Any]:
    rows = session.execute(
        select(PaymentLine, Employee.external_id)
        .join(Payslip, Payslip.id == PaymentLine.payslip_id)
        .join(Employee, Employee.id == Payslip.employee_id)
        .where(PaymentLine.run_id == run.id)
        .order_by(Employee.external_id)
    ).all()
    batches = session.scalars(
        select(PaymentBatch)
        .where(PaymentBatch.run_id == run.id)
        .order_by(PaymentBatch.release_number)
    )
    return {
        "run_status": run.status,
        "release": release_state(session, run),
        "notice": SANDBOX_NOTICE,
        "lines": [
            {
                "id": str(line.id),
                "employee": external,
                "amount": _text(line.amount),
                "status": line.status,
                "failure_reason": line.failure_reason,
                "destination": mask(line.bank_ref_token),
            }
            for line, external in rows
        ],
        "batches": [
            {
                "release_number": b.release_number,
                "provider_ref": b.provider_ref,
                "total": _text(b.total),
                "lines": b.line_count,
            }
            for b in batches
        ],
        "open_issues": [
            {"code": i.code, "field": i.field, "message": i.message, "next_action": i.next_action}
            for i in issues.open_for(session, ENTITY, run.id)
        ],
    }


def request_close(session: Session, tenant_id: UUID, actor: Actor, run_id: UUID) -> trust.Proposal:
    """Propose closing a fully paid run (R2). A closed run never changes again."""
    run = session.get(PayrollRun, run_id, with_for_update=True)
    if run is None:
        raise NotFound("Payroll run not found")
    if run.status != "paid":
        raise Conflict(f"The run is {run.status.replace('_', ' ')}, not paid")
    if issues.open_for(session, ENTITY, run.id):
        raise Conflict("Payment problems must be settled before the run is closed")
    attempt = proposals.next_attempt(
        session, actor, f"{CLOSE_ACTION}:{run.id}:", f"Closing run {run.id}"
    )
    lines = _lines(session, run.id)
    decision = explain.record(
        session,
        tenant_id,
        explain.DecisionDraft(
            kind="finance.payroll.close",
            question="Should this paid payroll run be closed?",
            outcome={
                "payments": str(len(lines)),
                "paid": str(sum(item.status == "paid" for item in lines)),
            },
            rationale=(
                f"All {len(lines)} payments of the run for {run.period_start.isoformat()} to "
                f"{run.period_end.isoformat()} are reconciled as paid. Closing makes it immutable."
            ),
            limits=[SANDBOX_NOTICE],
            view_roles=DECISION_VIEW_ROLES,
        ),
    )
    return trust.propose(
        session,
        tenant_id,
        CLOSE_ACTION,
        {"run_id": str(run.id)},
        "Close the paid payroll run",
        decision.id,
        f"{CLOSE_ACTION}:{run.id}:{attempt}",
        requested_by=actor.user_id,
    )


def close(session: Session, tenant_id: UUID, run_id: UUID) -> PayrollRun:
    """Worker only, after approval. Re-checks that every payment is still paid and settled."""
    run = session.get(PayrollRun, run_id, with_for_update=True)
    if run is None or run.status != "paid":
        raise Conflict("The run is not paid")
    lines = _lines(session, run.id)
    if not lines or any(line.status != "paid" for line in lines):
        raise Conflict("Not every payment is paid")
    if issues.open_for(session, ENTITY, run.id):
        raise Conflict("Payment problems are still open")
    run.status = "closed"
    session.flush()
    publish(session, tenant_id, PayrollClosed(run_id=run.id))
    return run
