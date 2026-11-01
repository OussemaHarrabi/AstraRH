"""Inbox API: the digest, the conversation list, and a person's decisions about it."""

from datetime import datetime
from typing import Any, Literal, get_args
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select

from kernel import comms, trust
from kernel.authz import require_role
from kernel.comms.models import Attachment, Classification, Digest, Message, Thread
from kernel.comms.vocabulary import MessageType
from kernel.db import utcnow
from kernel.errors import Conflict, NotFound
from kernel.trust.models import Proposal
from kernel.web import request_context

INBOX_ROLES = {"admin", "hr", "recruiter"}
URGENCIES = ("high", "normal", "low")
PAGE = 50

router = APIRouter(prefix="/comms", tags=["inbox"])


class HandledBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class CorrectionBody(BaseModel):
    type: MessageType | None = None
    urgency: Literal["high", "normal", "low"] | None = None
    needs_human: bool | None = None
    reason: str | None = Field(default=None, max_length=500)


def _classification_json(c: Classification | None) -> dict[str, Any] | None:
    if c is None:
        return None
    return {
        "type": c.type,
        "urgency": c.urgency,
        "needs_human": c.needs_human,
        "human_reason": c.human_reason,
        "summary": c.summary,
        "quote": c.quote,
        "flagged": c.flagged,
        "flags": c.flags,
        "corrected": c.corrected_at is not None,
        "model_values": c.model_values,
    }


def _thread_head(thread: Thread) -> dict[str, Any]:
    return {
        "id": str(thread.id),
        "subject": thread.subject,
        "party_email": thread.party_email,
        "status": thread.status,
        "last_message_at": thread.last_message_at.isoformat(),
        "handled_at": thread.handled_at.isoformat() if thread.handled_at else None,
        "handled_by": str(thread.handled_by) if thread.handled_by else None,
        "handled_note": thread.handled_note,
    }


def _pending_replies(session, thread_ids: list[UUID]) -> dict[str, list[str]]:
    rows = session.execute(
        select(Proposal.id, Proposal.target["thread_id"].astext).where(
            Proposal.action_type == "kernel.email.send",
            Proposal.status == "pending_approval",
            Proposal.target["thread_id"].astext.in_([str(t) for t in thread_ids]),
        )
    ).all()
    pending: dict[str, list[str]] = {}
    for proposal_id, thread_id in rows:
        pending.setdefault(thread_id, []).append(str(proposal_id))
    return pending


@router.get("/digest", summary="Today's digest, grouped by type, most urgent first")
def get_digest(request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INBOX_ROLES)
        digest = ctx.session.scalar(select(Digest).where(Digest.day == utcnow().date()))
        if digest is None:
            digest = comms.build_digest(ctx.session, ctx.actor.tenant_id)
        return comms.digest_view(ctx.session, digest)


@router.post("/digest", summary="Rebuild today's digest with the latest messages")
def rebuild_digest(request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INBOX_ROLES)
        digest = comms.build_digest(ctx.session, ctx.actor.tenant_id)
        trust.log_action(
            ctx.session,
            ctx.actor.tenant_id,
            "kernel.email.digest",
            "human",
            str(ctx.actor.user_id),
            data={"day": digest.day.isoformat()},
        )
        return comms.digest_view(ctx.session, digest)


@router.get("/stats", summary="Inbox counts for a dashboard, plus the sorting vocabulary")
def inbox_stats(request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INBOX_ROLES)
        session = ctx.session
        by_status = dict(
            session.execute(select(Thread.status, func.count()).group_by(Thread.status)).all()
        )
        open_inbound = (
            select(Classification)
            .join(Message, Message.id == Classification.message_id)
            .join(Thread, Thread.id == Message.thread_id)
            .where(Thread.status == "open", Message.direction == "in")
            .subquery()
        )
        by_type = dict(
            session.execute(
                select(
                    open_inbound.c.type, func.count(func.distinct(open_inbound.c.message_id))
                ).group_by(open_inbound.c.type)
            ).all()
        )
        needs_human = session.scalar(
            select(func.count(func.distinct(Message.thread_id)))
            .join(Classification, Classification.message_id == Message.id)
            .join(Thread, Thread.id == Message.thread_id)
            .where(Thread.status == "open", Classification.needs_human)
        )
        flagged = session.scalar(
            select(func.count()).select_from(Classification).where(Classification.flagged)
        )
        corrected = session.scalar(
            select(func.count())
            .select_from(Classification)
            .where(Classification.corrected_at.is_not(None))
        )
        classified = session.scalar(select(func.count()).select_from(Classification))
        return {
            "threads": {"open": by_status.get("open", 0), "handled": by_status.get("handled", 0)},
            "open_needing_a_person": needs_human,
            "open_messages_by_type": by_type,
            "flagged_messages": flagged,
            "classified_messages": classified,
            "corrected_by_a_person": corrected,
            "types": list(get_args(MessageType)),
            "urgencies": list(URGENCIES),
        }


@router.get("/threads", summary="Conversations, newest first, with their latest sorting")
def list_threads(
    request: Request,
    status: Literal["open", "handled", "all"] = "open",
    needs_human: bool | None = None,
    type: MessageType | None = None,  # noqa: A002 - the API field is called type
    q: str | None = Query(default=None, max_length=200),
    before: datetime | None = None,
    limit: int = Query(default=PAGE, ge=1, le=100),
) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INBOX_ROLES)
        session = ctx.session
        query = select(Thread)
        if status != "all":
            query = query.where(Thread.status == status)
        if needs_human is not None or type is not None:
            match = (
                select(Message.id)
                .join(Classification, Classification.message_id == Message.id)
                .where(Message.thread_id == Thread.id)
            )
            if needs_human is not None:
                match = match.where(Classification.needs_human.is_(needs_human))
            if type is not None:
                match = match.where(Classification.type == type)
            query = query.where(exists(match))
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            query = query.where(
                or_(Thread.subject.ilike(pattern), Thread.party_email.ilike(pattern))
            )
        if before is not None:
            query = query.where(Thread.last_message_at < before)
        threads = session.scalars(
            query.order_by(Thread.last_message_at.desc(), Thread.id).limit(limit + 1)
        ).all()
        more = len(threads) > limit
        threads = threads[:limit]
        ids = [t.id for t in threads]
        counts = dict(
            session.execute(
                select(Message.thread_id, func.count())
                .where(Message.thread_id.in_(ids))
                .group_by(Message.thread_id)
            ).all()
        )
        latest = {
            message.thread_id: (message, classification)
            for message, classification in session.execute(
                select(Message, Classification)
                .outerjoin(Classification, Classification.message_id == Message.id)
                .where(Message.thread_id.in_(ids), Message.direction == "in")
                .order_by(Message.thread_id, Message.sent_at.desc())
                .distinct(Message.thread_id)
            ).all()
        }
        pending = _pending_replies(session, ids)
        items = []
        for thread in threads:
            message, classification = latest.get(thread.id, (None, None))
            items.append(
                _thread_head(thread)
                | {
                    "messages": counts.get(thread.id, 0),
                    "latest_inbound": (
                        {
                            "message_id": str(message.id),
                            "sender": message.sender,
                            "sent_at": message.sent_at.isoformat(),
                            "sorting": _classification_json(classification),
                        }
                        if message
                        else None
                    ),
                    "pending_reply_ids": pending.get(str(thread.id), []),
                }
            )
        return {
            "items": items,
            "next_before": threads[-1].last_message_at.isoformat() if more and threads else None,
        }


def _thread_or_404(session, thread_id: UUID) -> Thread:
    thread = session.get(Thread, thread_id, with_for_update=True)
    if thread is None:
        raise NotFound("Conversation not found")
    return thread


@router.get("/threads/{thread_id}", summary="One conversation, with any reply awaiting approval")
def get_thread(thread_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INBOX_ROLES)
        session = ctx.session
        thread = session.get(Thread, thread_id)
        if thread is None:
            raise NotFound("Conversation not found")
        messages = session.scalars(
            select(Message).where(Message.thread_id == thread_id).order_by(Message.sent_at)
        ).all()
        classes = {
            c.message_id: c
            for c in session.scalars(
                select(Classification).where(
                    Classification.message_id.in_([m.id for m in messages])
                )
            )
        }
        attached: dict[UUID, list[dict[str, Any]]] = {}
        for a in session.scalars(
            select(Attachment)
            .where(Attachment.message_id.in_([m.id for m in messages]))
            .order_by(Attachment.created_at)
        ):
            attached.setdefault(a.message_id, []).append(
                {
                    "id": str(a.id),
                    "filename": a.filename,
                    "size": a.size,
                    "status": a.status,
                    "reason": a.reason,
                    "used_for": a.used_for,
                }
            )
        out = []
        for m in messages:
            c = classes.get(m.id)
            out.append(
                {
                    "id": str(m.id),
                    "direction": m.direction,
                    "sender": m.sender,
                    "recipient": m.recipient,
                    "subject": m.subject,
                    "body": m.body,
                    "sent_at": m.sent_at.isoformat(),
                    "sorting": _classification_json(c),
                    "attachments": attached.get(m.id, []),
                    # Kept flat for the first-pass web page.
                    "needs_human": c.needs_human if c else None,
                    "human_reason": c.human_reason if c else None,
                    "summary": c.summary if c else None,
                    "flagged": c.flagged if c else False,
                }
            )
        return _thread_head(thread) | {
            "messages": out,
            "pending_reply_ids": _pending_replies(session, [thread.id]).get(str(thread.id), []),
        }


@router.post("/threads/{thread_id}/handled", summary="Mark a conversation as dealt with")
def mark_handled(thread_id: UUID, body: HandledBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INBOX_ROLES)
        thread = _thread_or_404(ctx.session, thread_id)
        if thread.status == "handled":
            raise Conflict("This conversation is already handled")
        comms.mark_handled(thread, ctx.actor.user_id, body.note)
        trust.log_action(
            ctx.session,
            ctx.actor.tenant_id,
            "kernel.email.handle",
            "human",
            str(ctx.actor.user_id),
            data={"thread_id": str(thread.id), "status": "handled"},
        )
        return _thread_head(thread)


@router.post("/threads/{thread_id}/reopen", summary="Put a conversation back in the open list")
def reopen(thread_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INBOX_ROLES)
        thread = _thread_or_404(ctx.session, thread_id)
        if thread.status == "open":
            raise Conflict("This conversation is already open")
        comms.reopen(thread)
        trust.log_action(
            ctx.session,
            ctx.actor.tenant_id,
            "kernel.email.handle",
            "human",
            str(ctx.actor.user_id),
            data={"thread_id": str(thread.id), "status": "open"},
        )
        return _thread_head(thread)


@router.put(
    "/messages/{message_id}/sorting",
    summary="Correct the type, urgency or needs-a-person flag the assistant gave an email",
)
def correct_sorting(message_id: UUID, body: CorrectionBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INBOX_ROLES)
        session = ctx.session
        classification = session.scalar(
            select(Classification).where(Classification.message_id == message_id).with_for_update()
        )
        if classification is None:
            raise NotFound("No sorting for this message yet")
        changes: dict[str, Any] = {
            field: value
            for field, value in (
                ("type", body.type),
                ("urgency", body.urgency),
                ("needs_human", body.needs_human),
            )
            if value is not None
        }
        needs_human = changes.get("needs_human", classification.needs_human)
        if needs_human:
            if body.reason or not classification.human_reason:
                changes["human_reason"] = body.reason or "Marked by a person"
        else:
            changes["human_reason"] = None
        if not changes or all(getattr(classification, k) == v for k, v in changes.items()):
            raise Conflict("Nothing to change")
        comms.correct(session, classification, ctx.actor.user_id, changes)
        trust.log_action(
            session,
            ctx.actor.tenant_id,
            "kernel.email.correct",
            "human",
            str(ctx.actor.user_id),
            data={"message_id": str(message_id), "changes": sorted(changes)},
        )
        return {"message_id": str(message_id), "sorting": _classification_json(classification)}
