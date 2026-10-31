"""Inbox: threads and messages, classification and the daily digest. Used by every service."""

import re
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from kernel.comms.models import Classification, Digest, DigestItem, Message, Thread
from kernel.db import utcnow
from kernel.events import EventOutbox, event_type, publish, subscribe
from kernel.trust.models import Proposal

__all__ = [
    "Classification",
    "Digest",
    "DigestItem",
    "Message",
    "Thread",
    "build_digest",
    "force_human_reason",
    "ingest",
]

URGENCY_ORDER = {"high": 0, "normal": 1, "low": 2}
DIGEST_WINDOW = timedelta(days=7)
REPLY_PREFIX = re.compile(r"^\s*(re|fw|fwd|tr)\s*:\s*", re.IGNORECASE)

# Topics a person must always answer, even if the model doesn't flag them. This only adds flags:
# it can't remove one the model raised, so a miss here can't hide a message.
ALWAYS_HUMAN = {
    "Legal or a formal complaint": r"\b(lawyer|legal action|lawsuit|sue|court|avocat|tribunal|plainte|inspection du travail)\b",
    "Possible discrimination or harassment": r"\b(discriminat\w*|harass\w*|harcèlement|racis\w*|sexis\w*)\b",
    "Salary or an offer": r"\b(salary|salaire|compensation|rémunération|counter.?offer|contre.?offre|pay rise|negotiat\w*|négoci\w*)\b",
    "Visa or work permit": r"\b(visa|work permit|permis de travail|sponsorship|residence permit|carte de séjour)\b",
    "Health or disability": r"\b(disabilit\w*|handicap\w*|medical|pregnan\w*|enceinte|maternité|sick leave|congé maladie)\b",
    "Personal data request": r"\b(delete my data|my personal data|supprimer mes données|gdpr|rgpd|données personnelles)\b",
}
ALWAYS_HUMAN_COMPILED = {
    reason: re.compile(pattern, re.IGNORECASE) for reason, pattern in ALWAYS_HUMAN.items()
}


@event_type("comms.message.received.v1")
class MessageReceived(BaseModel):
    message_id: UUID
    thread_id: UUID


@event_type("comms.classification.corrected.v1")
class ClassificationCorrected(BaseModel):
    message_id: UUID
    corrected_by: UUID
    before: dict[str, Any]
    after: dict[str, Any]


@event_type("comms.message.classified.v1")
class MessageClassified(BaseModel):
    message_id: UUID
    thread_id: UUID
    type: str
    urgency: str
    needs_human: bool


def force_human_reason(text: str) -> str | None:
    for reason, pattern in ALWAYS_HUMAN_COMPILED.items():
        if pattern.search(text):
            return reason
    return None


def _normalized_subject(subject: str) -> str:
    current = subject.strip()
    while REPLY_PREFIX.match(current):
        current = REPLY_PREFIX.sub("", current).strip()
    return current.casefold()


def _thread_for(
    session: Session, tenant_id: UUID, party: str, subject: str, at: datetime
) -> Thread:
    wanted = _normalized_subject(subject)
    candidates = session.scalars(select(Thread).where(Thread.party_email == party)).all()
    for thread in candidates:
        if _normalized_subject(thread.subject) == wanted:
            thread.last_message_at = max(thread.last_message_at, at)
            return thread
    thread = Thread(tenant_id=tenant_id, subject=subject, party_email=party, last_message_at=at)
    session.add(thread)
    session.flush()
    return thread


def ingest(
    session: Session,
    tenant_id: UUID,
    provider_id: str,
    direction: str,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    sent_at: datetime | None = None,
    thread_id: UUID | None = None,
) -> Message | None:
    """Store one message. Returns None for a message already stored, so re-delivery is safe."""
    if session.scalar(select(Message.id).where(Message.provider_id == provider_id)):
        return None
    at = sent_at or utcnow()
    party = (sender if direction == "in" else recipient).lower()
    thread = session.get(Thread, thread_id) if thread_id else None
    if thread is None:
        thread = _thread_for(session, tenant_id, party, subject, at)
    else:
        thread.last_message_at = max(thread.last_message_at, at)
    message = Message(
        tenant_id=tenant_id,
        thread_id=thread.id,
        provider_id=provider_id,
        direction=direction,
        sender=sender.lower(),
        recipient=recipient.lower(),
        subject=subject,
        body=body,
        sent_at=at,
    )
    session.add(message)
    session.flush()
    if direction == "in":
        reopen(thread)
        publish(session, tenant_id, MessageReceived(message_id=message.id, thread_id=thread.id))
    return message


def mark_handled(thread: Thread, user_id: UUID | None, note: str | None = None) -> None:
    thread.status = "handled"
    thread.handled_by = user_id
    thread.handled_at = utcnow()
    thread.handled_note = note


def reopen(thread: Thread) -> None:
    thread.status = "open"
    thread.handled_by = None
    thread.handled_at = None
    thread.handled_note = None


SORTING_FIELDS = ("type", "urgency", "needs_human", "human_reason")


def correct(
    session: Session,
    classification: Classification,
    user_id: UUID,
    changes: dict[str, Any],
) -> Classification:
    """A person's sorting replaces the model's. The first model answer is kept for evals."""
    before = {field: getattr(classification, field) for field in SORTING_FIELDS}
    if classification.model_values is None:
        classification.model_values = before
    for field, value in changes.items():
        setattr(classification, field, value)
    classification.corrected_by = user_id
    classification.corrected_at = utcnow()
    after = {field: getattr(classification, field) for field in SORTING_FIELDS}
    publish(
        session,
        classification.tenant_id,
        ClassificationCorrected(
            message_id=classification.message_id, corrected_by=user_id, before=before, after=after
        ),
    )
    return classification


def build_digest(session: Session, tenant_id: UUID, day: date | None = None) -> Digest:
    """Grouping is deterministic: it uses stored classifications and makes no model call."""
    day = day or utcnow().date()
    since = utcnow() - DIGEST_WINDOW
    rows = session.execute(
        select(Classification, Message)
        .join(Message, Message.id == Classification.message_id)
        .where(Message.sent_at >= since, Message.direction == "in")
    ).all()
    totals = {
        "messages": len(rows),
        "needs_human": sum(1 for c, _ in rows if c.needs_human),
        "high_urgency": sum(1 for c, _ in rows if c.urgency == "high"),
        "flagged": sum(1 for c, _ in rows if c.flagged),
    }
    session.execute(
        insert(Digest)
        .values(tenant_id=tenant_id, day=day, totals=totals)
        .on_conflict_do_update(index_elements=["tenant_id", "day"], set_={"totals": totals})
    )
    digest = session.scalar(select(Digest).where(Digest.day == day))
    session.refresh(digest)
    for _, message in rows:
        session.execute(
            insert(DigestItem)
            .values(tenant_id=tenant_id, digest_id=digest.id, message_id=message.id)
            .on_conflict_do_nothing(index_elements=["digest_id", "message_id"])
        )
    return digest


def digest_view(session: Session, digest: Digest) -> dict[str, Any]:
    rows = session.execute(
        select(Classification, Message)
        .join(Message, Message.id == Classification.message_id)
        .join(DigestItem, DigestItem.message_id == Message.id)
        .where(DigestItem.digest_id == digest.id)
    ).all()
    statuses = dict(
        session.execute(
            select(Thread.id, Thread.status).where(
                Thread.id.in_({message.thread_id for _, message in rows})
            )
        ).all()
    )
    items = sorted(
        rows,
        key=lambda pair: (
            not pair[0].needs_human,
            URGENCY_ORDER.get(pair[0].urgency, 1),
            -pair[1].sent_at.timestamp(),
        ),
    )
    groups: dict[str, list[dict[str, Any]]] = {}
    for classification, message in items:
        groups.setdefault(classification.type, []).append(
            {
                "message_id": str(message.id),
                "thread_id": str(message.thread_id),
                "sender": message.sender,
                "subject": message.subject,
                "summary": classification.summary,
                "urgency": classification.urgency,
                "needs_human": classification.needs_human,
                "human_reason": classification.human_reason,
                "flagged": classification.flagged,
                "corrected": classification.corrected_at is not None,
                "thread_status": statuses.get(message.thread_id, "open"),
                "sent_at": message.sent_at.isoformat(),
            }
        )
    return {"day": digest.day.isoformat(), "totals": digest.totals, "groups": groups}


@subscribe("trust.action.executed.v1", "comms.record_outbound")
def record_outbound(session: Session, event: EventOutbox) -> None:
    """An approved email that went out belongs in its thread, which also stops its follow-ups."""
    if event.payload["action_type"] != "kernel.email.send":
        return
    proposal = session.get(Proposal, UUID(event.payload["proposal_id"]))
    payload = proposal.payload
    sent = ingest(
        session,
        event.tenant_id,
        f"sent:{proposal.id}",
        "out",
        "no-reply@cds.example.test",
        payload["to"],
        payload["subject"],
        payload["body"],
        thread_id=UUID(proposal.target["thread_id"]) if proposal.target.get("thread_id") else None,
    )
    if sent is not None and proposal.target.get("thread_id"):
        # A reply a person approved answers the conversation. Reminders and invites don't.
        mark_handled(session.get(Thread, sent.thread_id), None, "Approved reply sent")
