"""Engagements: create, validate, document, activate and amend. Shared by the API, the handlers,
the event consumer and the tests."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel import explain, trust
from kernel.canonical import payload_hash
from kernel.db import utcnow
from kernel.errors import Conflict, NotFound, ValidationFailed
from kernel.events import publish
from kernel.identity import Actor
from kernel.people.models import Employee
from packs.finance import issues, proposals
from packs.finance.events import (
    EngagementAmended,
    EngagementEndingSoon,
    EngagementTerminated,
    EngagementValidated,
)
from packs.finance.models import (
    DocumentRef,
    Engagement,
    EngagementAmendment,
    HireNotice,
    PayItem,
    ValidationIssue,
)
from packs.finance.validation import engagement as rules

ACTIVATE_ACTION = "finance.engagement.activate"
AMEND_ACTION = "finance.engagement.amend"
DECISION_VIEW_ROLES = ["admin", "finance", "hr", "auditor"]
BASE_SALARY = "BASE_SALARY"
EDITABLE = {"draft", "pending_review", "approved"}
LOCKED = {"active", "completed", "terminated"}
DOCUMENT_DECISIONS = {"verified", "rejected"}
AMENDABLE_FIELDS = {"base_salary", "weekly_hours", "job_title", "work_location", "ends_on"}


@dataclass
class PayItemInput:
    code: str
    amount: Decimal
    valid_from: date
    valid_to: date | None = None
    frequency: str = "monthly"


@dataclass
class NewEngagement:
    type: str
    starts_on: date
    job_title: str
    ends_on: date | None = None
    work_location: str | None = None
    weekly_hours: Decimal | None = None
    cdd_reason_code: str | None = None
    head_of_family: bool = False
    children: list[str] = field(default_factory=list)
    external_request_id: str | None = None
    source_event_id: str | None = None
    pay_items: list[PayItemInput] = field(default_factory=list)


def get_engagement(session: Session, engagement_id: UUID) -> Engagement:
    row = session.get(Engagement, engagement_id)
    if row is None:
        raise NotFound("Engagement not found")
    return row


def pay_items_of(session: Session, engagement_id: UUID) -> list[PayItem]:
    return _items(session, engagement_id)


def _items(session: Session, engagement_id: UUID) -> list[PayItem]:
    return list(
        session.scalars(
            select(PayItem)
            .where(PayItem.engagement_id == engagement_id)
            .order_by(PayItem.code, PayItem.valid_from)
        )
    )


def _documents(session: Session, engagement_id: UUID) -> list[DocumentRef]:
    return list(
        session.scalars(
            select(DocumentRef)
            .where(DocumentRef.engagement_id == engagement_id)
            .order_by(DocumentRef.created_at)
        )
    )


def create_engagement(
    session: Session, tenant_id: UUID, employee_id: UUID, data: NewEngagement
) -> tuple[Engagement, bool]:
    """Returns the engagement and whether it was new. The same request id returns the same row."""
    if session.get(Employee, employee_id) is None:
        raise NotFound("Employee not found")
    if data.external_request_id:
        existing = session.scalar(
            select(Engagement).where(Engagement.external_request_id == data.external_request_id)
        )
        if existing is not None:
            if existing.employee_id != employee_id:
                raise Conflict("That request id was used for a different employee")
            return existing, False
    row = Engagement(
        tenant_id=tenant_id,
        employee_id=employee_id,
        type=data.type,
        starts_on=data.starts_on,
        ends_on=data.ends_on,
        job_title=data.job_title,
        work_location=data.work_location,
        weekly_hours=data.weekly_hours,
        cdd_reason_code=data.cdd_reason_code,
        head_of_family=data.head_of_family,
        children=list(data.children),
        external_request_id=data.external_request_id,
        source_event_id=data.source_event_id,
    )
    session.add(row)
    session.flush()
    for item in data.pay_items:
        add_pay_item(session, tenant_id, row, item, revalidate=False)
    validate_engagement(session, tenant_id, row)
    return row, True


def add_pay_item(
    session: Session,
    tenant_id: UUID,
    engagement: Engagement,
    item: PayItemInput,
    revalidate: bool = True,
) -> PayItem:
    if engagement.status in LOCKED:
        raise Conflict("Pay of an active engagement changes only through an approved amendment")
    if item.amount <= 0:
        raise ValidationFailed("A pay item must be above zero")
    if item.valid_to is not None and item.valid_to < item.valid_from:
        raise ValidationFailed("A pay item cannot end before it starts")
    for other in _items(session, engagement.id):
        if other.code != item.code:
            continue
        ends = other.valid_to or date.max
        if item.valid_from <= ends and (item.valid_to or date.max) >= other.valid_from:
            raise Conflict(f"{item.code} already has a period that overlaps these dates")
    row = PayItem(
        tenant_id=tenant_id,
        engagement_id=engagement.id,
        code=item.code,
        amount=item.amount,
        frequency=item.frequency,
        valid_from=item.valid_from,
        valid_to=item.valid_to,
    )
    session.add(row)
    session.flush()
    if revalidate:
        validate_engagement(session, tenant_id, engagement)
    return row


def _view(session: Session, engagement: Engagement) -> rules.EngagementView:
    items = _items(session, engagement.id)
    has_salary = any(
        item.code == BASE_SALARY
        and item.valid_from <= engagement.starts_on
        and (item.valid_to is None or item.valid_to >= engagement.starts_on)
        for item in items
    )
    verified = frozenset(
        doc.doc_type
        for doc in _documents(session, engagement.id)
        if doc.verification_status == "verified"
    )
    base_salary = next(
        (
            item.amount
            for item in items
            if item.code == BASE_SALARY
            and item.valid_from <= engagement.starts_on
            and (item.valid_to is None or item.valid_to >= engagement.starts_on)
        ),
        None,
    )
    return rules.EngagementView(
        type=engagement.type,
        starts_on=engagement.starts_on,
        ends_on=engagement.ends_on,
        job_title=engagement.job_title,
        weekly_hours=engagement.weekly_hours,
        cdd_reason_code=engagement.cdd_reason_code,
        has_base_salary=has_salary,
        verified_documents=verified,
        base_salary=base_salary,
    )


def open_issues(session: Session, engagement_id: UUID) -> list[ValidationIssue]:
    return issues.open_for(session, "engagement", engagement_id)


def validate_engagement(session: Session, tenant_id: UUID, engagement: Engagement) -> Engagement:
    """Idempotent. Updates the issues and, before activation, the status they imply."""
    if engagement.status in LOCKED:
        return engagement
    issues.sync(
        session, tenant_id, "engagement", engagement.id, rules.validate(_view(session, engagement))
    )
    pending = open_issues(session, engagement.id)
    blocking = sum(1 for i in pending if i.severity == rules.BLOCKING)
    review = sum(1 for i in pending if i.severity == rules.REVIEW)
    engagement.status = "draft" if blocking else "pending_review" if review else "approved"
    session.flush()
    publish(
        session,
        tenant_id,
        EngagementValidated(
            engagement_id=engagement.id, status=engagement.status, blocking=blocking, review=review
        ),
    )
    return engagement


def add_document(
    session: Session,
    tenant_id: UUID,
    engagement: Engagement,
    doc_type: str,
    note: str | None = None,
    file_key: str | None = None,
) -> DocumentRef:
    if doc_type not in rules.DOCUMENT_TYPES:
        raise ValidationFailed(f"Unknown document type {doc_type!r}")
    if engagement.status in LOCKED:
        raise Conflict("Documents of an active engagement are not changed here")
    row = DocumentRef(
        tenant_id=tenant_id,
        employee_id=engagement.employee_id,
        engagement_id=engagement.id,
        doc_type=doc_type,
        note=note,
        file_key=file_key,
    )
    session.add(row)
    session.flush()
    validate_engagement(session, tenant_id, engagement)
    return row


def review_document(
    session: Session, actor: Actor, document_id: UUID, decision: str, note: str | None = None
) -> DocumentRef:
    if decision not in DOCUMENT_DECISIONS:
        raise ValidationFailed("Decide verified or rejected")
    document = session.get(DocumentRef, document_id)
    if document is None or document.engagement_id is None:
        raise NotFound("Document not found")
    engagement = get_engagement(session, document.engagement_id)
    if engagement.status in LOCKED:
        raise Conflict("Documents of an active engagement are not changed here")
    document.verification_status = decision
    document.verified_by = actor.user_id
    document.verified_at = utcnow()
    if note:
        document.note = note
    session.flush()
    validate_engagement(session, actor.tenant_id, engagement)
    return document


def checklist(session: Session, engagement: Engagement) -> list[dict[str, Any]]:
    documents = _documents(session, engagement.id)
    result = []
    for doc_type in rules.REQUIRED_DOCUMENTS.get(engagement.type, ()):
        of_type = [d for d in documents if d.doc_type == doc_type]
        result.append(
            {
                "doc_type": doc_type,
                "present": bool(of_type),
                "verified": any(d.verification_status == "verified" for d in of_type),
            }
        )
    return result


def terms_hash(session: Session, engagement: Engagement) -> str:
    """Binds an approval to the exact terms, so a later edit cannot ride on it."""
    return payload_hash(
        {
            "employee_id": str(engagement.employee_id),
            "type": engagement.type,
            "starts_on": engagement.starts_on.isoformat(),
            "ends_on": engagement.ends_on.isoformat() if engagement.ends_on else None,
            "job_title": engagement.job_title,
            "weekly_hours": str(engagement.weekly_hours),
            "cdd_reason_code": engagement.cdd_reason_code,
            "head_of_family": engagement.head_of_family,
            "children": list(engagement.children),
            "pay_items": [
                [i.code, str(i.amount), i.valid_from.isoformat(), str(i.valid_to)]
                for i in _items(session, engagement.id)
            ],
        }
    )


def request_activation(
    session: Session, tenant_id: UUID, actor: Actor, engagement_id: UUID
) -> trust.Proposal:
    """Propose activation (R2). Nothing changes until a person approves it."""
    engagement = get_engagement(session, engagement_id)
    validate_engagement(session, tenant_id, engagement)
    if engagement.status != "approved":
        remaining = [f"{i.code} ({i.severity})" for i in open_issues(session, engagement.id)]
        raise Conflict(
            f"The engagement is {engagement.status}, not ready to activate. Open: "
            + ", ".join(remaining)
        )
    terms = terms_hash(session, engagement)
    attempt = proposals.next_attempt(
        session, actor, f"{ACTIVATE_ACTION}:{engagement.id}:", f"Engagement {engagement.id}"
    )
    resolved = session.scalars(
        select(ValidationIssue).where(
            ValidationIssue.entity_type == "engagement",
            ValidationIssue.entity_id == engagement.id,
            ValidationIssue.status == "resolved",
        )
    ).all()
    verified = sum(1 for item in checklist(session, engagement) if item["verified"])
    notes = "; ".join(f"{i.code}: {i.resolution_reason}" for i in resolved) or "none"
    limits = [
        "The system checks fields and documents. Whether the contract is legally valid is "
        "a human decision."
    ]
    if engagement.type == "CDD":
        limits.append("The fixed-term reason list is a placeholder, not the labour code.")
    decision = explain.record(
        session,
        tenant_id,
        explain.DecisionDraft(
            kind="finance.engagement.activation",
            question=f"Should this {engagement.type} engagement become active?",
            outcome={"type": engagement.type, "documents_verified": verified},
            rationale=(
                f"{engagement.type} from {engagement.starts_on.isoformat()}. "
                f"{verified} required documents verified. "
                f"Review items decided by a person: {notes}."
            ),
            limits=limits,
            versions={"terms_hash": terms},
            view_roles=DECISION_VIEW_ROLES,
        ),
    )
    return trust.propose(
        session,
        tenant_id,
        ACTIVATE_ACTION,
        {"engagement_id": str(engagement.id), "terms_hash": terms},
        f"Activate the {engagement.type} engagement",
        decision.id,
        f"{ACTIVATE_ACTION}:{engagement.id}:{terms[:16]}:{attempt}",
        requested_by=actor.user_id,
    )


def _amendment_value(field_name: str, raw: str) -> str:
    try:
        if field_name == "base_salary":
            amount = Decimal(raw)
            if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.001")):
                raise ValueError
            return format(amount, "f")
        if field_name == "weekly_hours":
            hours = Decimal(raw)
            if not hours.is_finite() or hours <= 0:
                raise ValueError
            return format(hours, "f")
        if field_name == "ends_on":
            return date.fromisoformat(raw).isoformat()
    except (InvalidOperation, ValueError):
        raise ValidationFailed(f"{raw!r} is not a valid value for {field_name}") from None
    if not raw.strip():
        raise ValidationFailed(f"{field_name} cannot be empty")
    return raw.strip()


def _current_value(
    session: Session, engagement: Engagement, field_name: str, day: date
) -> str | None:
    if field_name == "base_salary":
        for item in _items(session, engagement.id):
            if item.code == BASE_SALARY and item.valid_from <= day <= (item.valid_to or date.max):
                return format(item.amount, "f")
        return None
    value = getattr(engagement, field_name)
    return None if value is None else str(value)


def request_amendment(
    session: Session,
    tenant_id: UUID,
    actor: Actor,
    engagement_id: UUID,
    field_name: str,
    new_value: str,
    effective_from: date,
    reason: str,
) -> trust.Proposal:
    """Propose a change from a date (R2). History is kept: nothing is overwritten."""
    engagement = get_engagement(session, engagement_id)
    if engagement.status != "active":
        raise Conflict("Only an active engagement is amended. Edit a draft before it is activated")
    if field_name not in AMENDABLE_FIELDS:
        raise ValidationFailed(f"{field_name} cannot be amended")
    if effective_from < engagement.starts_on:
        raise ValidationFailed("A change cannot start before the engagement does")
    if len(reason.strip()) < 3:
        raise ValidationFailed("A reason is required")
    if field_name == "ends_on" and engagement.type != "CDD":
        raise ValidationFailed(
            "Only a CDD end date is amended here. A CIVP uses an extension request"
        )
    value = _amendment_value(field_name, new_value)
    payload = {
        "engagement_id": str(engagement.id),
        "field": field_name,
        "new_value": value,
        "effective_from": effective_from.isoformat(),
        "reason": reason.strip(),
    }
    attempt = proposals.next_attempt(
        session,
        actor,
        f"{AMEND_ACTION}:{engagement.id}:{payload_hash(payload)[:16]}:",
        f"This amendment of engagement {engagement.id}",
    )
    decision = explain.record(
        session,
        tenant_id,
        explain.DecisionDraft(
            kind="finance.engagement.amendment",
            question=f"Should {field_name} change from {effective_from.isoformat()}?",
            outcome={"field": field_name, "effective_from": effective_from.isoformat()},
            rationale=f"Requested reason: {reason.strip()}",
            limits=["The previous value stays in the history and earlier pay periods keep it."],
            view_roles=DECISION_VIEW_ROLES,
        ),
    )
    return trust.propose(
        session,
        tenant_id,
        AMEND_ACTION,
        payload,
        f"Change {field_name} of the engagement from {effective_from.isoformat()}",
        decision.id,
        f"{AMEND_ACTION}:{engagement.id}:{payload_hash(payload)[:16]}:{attempt}",
        requested_by=actor.user_id,
    )


def apply_amendment(
    session: Session,
    tenant_id: UUID,
    payload: dict[str, Any],
    requested_by: UUID,
    proposal_id: UUID,
) -> EngagementAmendment:
    """Runs only after approval, in the worker. Raises ValidationFailed or Conflict if it cannot."""
    engagement = session.get(Engagement, UUID(payload["engagement_id"]), with_for_update=True)
    if engagement is None or engagement.status != "active":
        raise Conflict("The engagement is no longer active")
    field_name = payload["field"]
    effective_from = date.fromisoformat(payload["effective_from"])
    value = _amendment_value(field_name, payload["new_value"])
    old = _current_value(session, engagement, field_name, effective_from)
    if field_name == "base_salary":
        items = [i for i in _items(session, engagement.id) if i.code == BASE_SALARY]
        current = next(
            (i for i in items if i.valid_from <= effective_from <= (i.valid_to or date.max)), None
        )
        if current is None:
            raise Conflict("There is no base salary in force on that date")
        if any(i.valid_from >= effective_from for i in items):
            raise Conflict("A pay change already starts on or after that date")
        current.valid_to = effective_from - timedelta(days=1)
        session.add(
            PayItem(
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                code=BASE_SALARY,
                amount=Decimal(value),
                frequency=current.frequency,
                valid_from=effective_from,
            )
        )
    elif field_name == "ends_on":
        engagement.ends_on = date.fromisoformat(value)
        if engagement.ends_on < engagement.starts_on:
            raise ValidationFailed("The end date is before the start date")
    elif field_name == "weekly_hours":
        engagement.weekly_hours = Decimal(value)
    else:
        setattr(engagement, field_name, value)
    amendment = EngagementAmendment(
        tenant_id=tenant_id,
        engagement_id=engagement.id,
        field=field_name,
        old_value=old,
        new_value=value,
        effective_from=effective_from,
        actor_id=requested_by,
        reason=payload["reason"],
        proposal_id=proposal_id,
    )
    session.add(amendment)
    session.flush()
    publish(
        session,
        tenant_id,
        EngagementAmended(engagement_id=engagement.id, effective_from=effective_from),
    )
    return amendment


def record_hire(
    session: Session,
    tenant_id: UUID,
    application_id: UUID,
    job_id: UUID,
    candidate_id: UUID,
    person_id: UUID,
    event_id: str,
) -> HireNotice | None:
    """One notice per application, however many times the event arrives."""
    if session.scalar(select(HireNotice.id).where(HireNotice.application_id == application_id)):
        return None
    notice = HireNotice(
        tenant_id=tenant_id,
        application_id=application_id,
        job_id=job_id,
        candidate_id=candidate_id,
        person_id=person_id,
        source_event_id=event_id,
    )
    session.add(notice)
    session.flush()
    return notice


def employee_of_person(session: Session, person_id: UUID) -> Employee | None:
    return session.scalar(select(Employee).where(Employee.person_id == person_id))


def convert_hire_notice(
    session: Session,
    tenant_id: UUID,
    notice_id: UUID,
    employee_id: UUID | None,
    data: NewEngagement,
) -> Engagement:
    """The employee is named by HR, or found from the hired person when one already exists."""
    notice = session.get(HireNotice, notice_id, with_for_update=True)
    if notice is None:
        raise NotFound("Hire notice not found")
    if notice.status != "awaiting_terms":
        raise Conflict("This hire notice already has an engagement")
    if employee_id is None:
        employee = notice.person_id and employee_of_person(session, notice.person_id)
        if not employee:
            raise Conflict(
                "There is no employee record for the hired person yet. Create it first, "
                "or give the employee id"
            )
        employee_id = employee.id
    else:
        known = session.get(Employee, employee_id)
        if known is not None and notice.person_id and known.person_id != notice.person_id:
            raise Conflict("That employee is a different person from the one who was hired")
    data.source_event_id = data.source_event_id or f"hire_notice:{notice.id}"
    engagement, _ = create_engagement(session, tenant_id, employee_id, data)
    notice.status = "converted"
    notice.engagement_id = engagement.id
    session.flush()
    return engagement


def edit_draft(
    session: Session,
    tenant_id: UUID,
    engagement_id: UUID,
    *,
    job_title: str | None = None,
    work_location: str | None = None,
    weekly_hours: Decimal | None = None,
    ends_on: date | None = None,
    base_salary: Decimal | None = None,
) -> Engagement:
    row = get_engagement(session, engagement_id)
    if row.status not in EDITABLE:
        raise Conflict("Only a draft or review engagement can be edited")
    if job_title is not None:
        row.job_title = job_title.strip()
    if work_location is not None:
        row.work_location = work_location.strip() or None
    if weekly_hours is not None:
        row.weekly_hours = weekly_hours
    if ends_on is not None:
        row.ends_on = ends_on
    if base_salary is not None:
        item = next((i for i in _items(session, row.id) if i.code == BASE_SALARY), None)
        if item is None:
            add_pay_item(
                session,
                tenant_id,
                row,
                PayItemInput(BASE_SALARY, base_salary, row.starts_on),
                revalidate=False,
            )
        else:
            item.amount = base_salary
    session.flush()
    return validate_engagement(session, tenant_id, row)


def terminate(session: Session, tenant_id: UUID, engagement_id: UUID, end_on: date, reason: str) -> Engagement:
    row = get_engagement(session, engagement_id)
    if row.status != "active":
        raise Conflict("Only an active engagement can be terminated")
    if end_on < row.starts_on:
        raise ValidationFailed("The termination date is before the engagement start")
    row.ends_on = end_on
    row.status = "terminated"
    session.flush()
    publish(session, tenant_id, EngagementTerminated(engagement_id=row.id, ends_on=end_on))
    return row


def ending_soon(session: Session, tenant_id: UUID, on: date, days: int = 30) -> list[Engagement]:
    rows = list(
        session.scalars(
            select(Engagement).where(
                Engagement.status == "active",
                Engagement.ends_on.is_not(None),
                Engagement.ends_on >= on,
                Engagement.ends_on <= on + timedelta(days=days),
            )
        )
    )
    for row in rows:
        publish(session, tenant_id, EngagementEndingSoon(engagement_id=row.id, ends_on=row.ends_on))
    return rows
