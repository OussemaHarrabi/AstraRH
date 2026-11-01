"""CIVP placement lifecycle and its separate payer ledger."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel import explain, trust
from kernel.db import utcnow
from kernel.errors import Conflict, NotFound, ValidationFailed
from kernel.events import publish
from kernel.identity import Actor
from packs.finance import engagements
from packs.finance.events import (
    CivpActivated,
    CivpCompleted,
    CivpPaymentDue,
    CivpPaymentReconciled,
)
from packs.finance.models import (
    CivpExtensionRequest,
    CivpLedgerEntry,
    CivpPlacement,
    CivpTraining,
    Engagement,
)

ACTIVATE_ACTION = "finance.civp.activate"
EXTENSION_ACTION = "finance.civp.extension.approve"
COMPLETE_ACTION = "finance.civp.complete"
CATEGORIES = {
    "higher_education": (Decimal("200.000"), Decimal("200.000")),
    "bts": (Decimal("200.000"), Decimal("200.000")),
    "other": (Decimal("150.000"), Decimal("150.000")),
}


def get_placement(session: Session, placement_id: UUID) -> CivpPlacement:
    placement = session.get(CivpPlacement, placement_id)
    if placement is None:
        raise NotFound("CIVP placement not found")
    return placement


def create_placement(
    session: Session,
    tenant_id: UUID,
    engagement_id: UUID,
    participant_category: str,
    aneti_reference: str | None,
    starts_on: date,
    ends_on: date,
    disabled_participant: bool = False,
    aneti_allowance_monthly: Decimal | None = None,
    employer_complement_monthly: Decimal | None = None,
    training_hours_limit: Decimal | None = None,
) -> CivpPlacement:
    engagement = session.get(Engagement, engagement_id)
    if engagement is None or engagement.type != "CIVP":
        raise ValidationFailed("A CIVP placement needs a CIVP engagement")
    if session.scalar(select(CivpPlacement.id).where(CivpPlacement.engagement_id == engagement_id)):
        raise Conflict("This engagement already has a CIVP placement")
    if ends_on < starts_on or (ends_on - starts_on).days > 365:
        raise ValidationFailed("A new CIVP placement cannot exceed twelve months")
    amounts = CATEGORIES.get(participant_category)
    if amounts is None:
        raise ValidationFailed("Unknown CIVP participant category")
    allowance = aneti_allowance_monthly or amounts[0]
    complement = employer_complement_monthly or amounts[1]
    if allowance <= 0 or complement <= 0:
        raise ValidationFailed("CIVP payer amounts must be positive")
    placement = CivpPlacement(
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        aneti_reference=aneti_reference,
        approval_status="aneti_pending",
        participant_category=participant_category,
        disabled_participant=disabled_participant,
        starts_on=starts_on,
        ends_on=ends_on,
        aneti_allowance_monthly=allowance,
        employer_complement_monthly=complement,
        training_hours_limit=training_hours_limit,
        status="draft",
    )
    session.add(placement)
    session.flush()
    return placement


def confirm_eligibility(session: Session, actor: Actor, placement_id: UUID) -> CivpPlacement:
    placement = get_placement(session, placement_id)
    if placement.status not in {"draft", "aneti_pending"}:
        raise Conflict("Eligibility can only be confirmed for a draft placement")
    if not placement.aneti_reference:
        raise ValidationFailed("Record the human-confirmed ANETI reference first")
    placement.approval_status = "approved"
    placement.eligibility_confirmed_by = actor.user_id
    placement.eligibility_confirmed_at = utcnow()
    session.flush()
    return placement


def request_activation(
    session: Session, tenant_id: UUID, actor: Actor, placement_id: UUID
) -> trust.Proposal:
    placement = get_placement(session, placement_id)
    if placement.approval_status != "approved":
        raise Conflict("ANETI approval and eligibility confirmation are required")
    if placement.status != "draft":
        raise Conflict(f"The placement is {placement.status}")
    decision = explain.record(
        session,
        tenant_id,
        explain.DecisionDraft(
            kind="finance.civp.activation",
            question="Should this CIVP placement become active?",
            outcome={"placement_id": str(placement.id)},
            rationale=(
                f"The placement runs from {placement.starts_on.isoformat()} to "
                f"{placement.ends_on.isoformat()} and has human-confirmed eligibility."
            ),
            limits=["CIVP amounts and duration are configurable demo values."],
            view_roles=["admin", "finance", "hr", "auditor"],
        ),
    )
    return trust.propose(
        session,
        tenant_id,
        ACTIVATE_ACTION,
        {"placement_id": str(placement.id)},
        "Activate the CIVP placement",
        decision.id,
        f"{ACTIVATE_ACTION}:{placement.id}",
        requested_by=actor.user_id,
    )


def activate(session: Session, tenant_id: UUID, placement_id: UUID) -> CivpPlacement:
    placement = get_placement(session, placement_id)
    if placement.approval_status != "approved" or placement.status != "draft":
        raise Conflict("The placement is not ready to activate")
    placement.status = "active"
    session.flush()
    publish(
        session,
        tenant_id,
        CivpActivated(
            placement_id=placement.id,
            engagement_id=placement.engagement_id,
            starts_on=placement.starts_on,
        ),
    )
    return placement


def _month(value: date) -> date:
    return value.replace(day=1)


def generate_month(session: Session, tenant_id: UUID, placement_id: UUID, month: date) -> list[CivpLedgerEntry]:
    placement = get_placement(session, placement_id)
    month = _month(month)
    if placement.status != "active" or not (placement.starts_on <= month <= placement.ends_on):
        raise Conflict("The placement is not active in that month")
    existing = {
        row.payer: row
        for row in session.scalars(
            select(CivpLedgerEntry).where(
                CivpLedgerEntry.placement_id == placement.id, CivpLedgerEntry.month == month
            )
        )
    }
    rows = []
    for payer, amount in (
        ("aneti", placement.aneti_allowance_monthly),
        ("employer", placement.employer_complement_monthly),
    ):
        row = existing.get(payer)
        if row is None:
            row = CivpLedgerEntry(
                tenant_id=tenant_id,
                placement_id=placement.id,
                month=month,
                payer=payer,
                due_amount=amount,
                paid_amount=Decimal("0.000"),
                status="due",
            )
            session.add(row)
            session.flush()
            publish(
                session,
                tenant_id,
                CivpPaymentDue(placement_id=placement.id, month=month, payer=payer),
            )
        rows.append(row)
    return rows


def reconcile_payment(
    session: Session,
    tenant_id: UUID,
    entry_id: UUID,
    paid_amount: Decimal,
    payment_ref: str,
) -> CivpLedgerEntry:
    entry = session.get(CivpLedgerEntry, entry_id, with_for_update=True)
    if entry is None:
        raise NotFound("CIVP ledger entry not found")
    if entry.status == "paid":
        return entry
    if paid_amount < 0 or paid_amount > entry.due_amount:
        raise ValidationFailed("A CIVP payment cannot exceed its due amount")
    entry.paid_amount = paid_amount
    entry.payment_ref = payment_ref
    entry.status = "paid" if paid_amount == entry.due_amount else "part_paid"
    session.flush()
    publish(
        session,
        tenant_id,
        CivpPaymentReconciled(
            placement_id=entry.placement_id,
            month=entry.month,
            payer=entry.payer,
            status=entry.status,
        ),
    )
    return entry


def record_training(
    session: Session,
    tenant_id: UUID,
    actor: Actor,
    placement_id: UUID,
    training_date: date,
    hours: Decimal,
    topic: str,
) -> CivpTraining:
    placement = get_placement(session, placement_id)
    if placement.status != "active":
        raise Conflict("Training can only be recorded on an active placement")
    if hours <= 0:
        raise ValidationFailed("Training hours must be positive")
    row = CivpTraining(
        tenant_id=tenant_id,
        placement_id=placement.id,
        training_date=training_date,
        hours=hours,
        topic=topic.strip(),
        recorded_by=actor.user_id,
    )
    session.add(row)
    session.flush()
    return row


def request_extension(
    session: Session, tenant_id: UUID, placement_id: UUID, requested_end: date, reason: str
) -> CivpExtensionRequest:
    placement = get_placement(session, placement_id)
    eligible = placement.disabled_participant and placement.participant_category in {
        "higher_education",
        "bts",
    }
    row = CivpExtensionRequest(
        tenant_id=tenant_id,
        placement_id=placement.id,
        requested_end=requested_end,
        reason=reason.strip(),
        status="pending" if eligible else "refused",
        decision_reason=None if eligible else "Only an eligible disabled higher-education or BTS participant may be extended.",
    )
    session.add(row)
    session.flush()
    return row


def decide_extension(
    session: Session, actor: Actor, request_id: UUID, approve: bool, reason: str
) -> CivpExtensionRequest:
    row = session.get(CivpExtensionRequest, request_id, with_for_update=True)
    if row is None:
        raise NotFound("CIVP extension request not found")
    if row.status != "pending":
        raise Conflict("This extension request is already decided")
    placement = get_placement(session, row.placement_id)
    row.status = "approved" if approve else "refused"
    row.decided_by = actor.user_id
    row.decided_at = utcnow()
    row.decision_reason = reason.strip()
    if approve:
        if row.requested_end <= placement.ends_on:
            raise ValidationFailed("An extension must move the end date forward")
        placement.ends_on = row.requested_end
        placement.status = "active"
    session.flush()
    return row


def request_completion(
    session: Session, tenant_id: UUID, actor: Actor, placement_id: UUID
) -> trust.Proposal:
    placement = get_placement(session, placement_id)
    if placement.status != "active":
        raise Conflict("Only an active placement can be completed")
    open_rows = session.scalar(
        select(CivpLedgerEntry.id).where(
            CivpLedgerEntry.placement_id == placement.id,
            CivpLedgerEntry.status != "paid",
        )
    )
    if open_rows:
        raise Conflict("All CIVP ledger rows must be paid before completion")
    decision = explain.record(
        session,
        tenant_id,
        explain.DecisionDraft(
            kind="finance.civp.completion",
            question="Should this CIVP placement be completed?",
            outcome={"placement_id": str(placement.id)},
            rationale="All generated CIVP payer ledger rows are reconciled as paid.",
            limits=["Completion does not create a CDI automatically."],
            view_roles=["admin", "finance", "hr", "auditor"],
        ),
    )
    return trust.propose(
        session,
        tenant_id,
        COMPLETE_ACTION,
        {"placement_id": str(placement.id)},
        "Complete the CIVP placement",
        decision.id,
        f"{COMPLETE_ACTION}:{placement.id}",
        requested_by=actor.user_id,
    )


def complete(session: Session, tenant_id: UUID, placement_id: UUID) -> CivpPlacement:
    placement = get_placement(session, placement_id)
    if placement.status != "active":
        raise Conflict("The placement is not active")
    if session.scalar(
        select(CivpLedgerEntry.id).where(
            CivpLedgerEntry.placement_id == placement.id,
            CivpLedgerEntry.status != "paid",
        )
    ):
        raise Conflict("All CIVP ledger rows must be paid before completion")
    placement.status = "completed"
    placement.completed_at = utcnow()
    engagement = session.get(Engagement, placement.engagement_id)
    if engagement is not None:
        engagement.status = "completed"
    session.flush()
    publish(
        session,
        tenant_id,
        CivpCompleted(placement_id=placement.id, engagement_id=placement.engagement_id),
    )
    return placement


def summary(session: Session, placement_id: UUID) -> dict[str, Any]:
    placement = get_placement(session, placement_id)
    ledger = list(
        session.scalars(
            select(CivpLedgerEntry)
            .where(CivpLedgerEntry.placement_id == placement.id)
            .order_by(CivpLedgerEntry.month, CivpLedgerEntry.payer)
        )
    )
    training = list(
        session.scalars(
            select(CivpTraining)
            .where(CivpTraining.placement_id == placement.id)
            .order_by(CivpTraining.training_date)
        )
    )
    return {
        "id": str(placement.id),
        "engagement_id": str(placement.engagement_id),
        "status": placement.status,
        "approval_status": placement.approval_status,
        "participant_category": placement.participant_category,
        "starts_on": placement.starts_on.isoformat(),
        "ends_on": placement.ends_on.isoformat(),
        "aneti_allowance_monthly": format(placement.aneti_allowance_monthly, "f"),
        "employer_complement_monthly": format(placement.employer_complement_monthly, "f"),
        "training_hours": format(sum((row.hours for row in training), Decimal(0)), "f"),
        "training_hours_limit": None if placement.training_hours_limit is None else format(placement.training_hours_limit, "f"),
        "ledger": [
            {
                "id": str(row.id),
                "month": row.month.isoformat(),
                "payer": row.payer,
                "due_amount": format(row.due_amount, "f"),
                "paid_amount": format(row.paid_amount, "f"),
                "status": row.status,
                "payment_ref": row.payment_ref,
            }
            for row in ledger
        ],
    }
