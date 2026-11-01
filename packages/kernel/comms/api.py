"""Inbox API."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from kernel import comms, trust
from kernel.authz import require_role
from kernel.comms.models import Classification, Digest, Message, Thread
from kernel.db import utcnow
from kernel.errors import NotFound
from kernel.trust.models import Proposal
from kernel.web import request_context

INBOX_ROLES = {"admin", "hr", "recruiter"}

router = APIRouter(prefix="/comms", tags=["inbox"])


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
        pending = session.scalars(
            select(Proposal).where(
                Proposal.action_type == "kernel.email.send",
                Proposal.status == "pending_approval",
                Proposal.target["thread_id"].astext == str(thread_id),
            )
        ).all()
        return {
            "id": str(thread.id),
            "subject": thread.subject,
            "party_email": thread.party_email,
            "messages": [
                {
                    "id": str(m.id),
                    "direction": m.direction,
                    "sender": m.sender,
                    "subject": m.subject,
                    "body": m.body,
                    "sent_at": m.sent_at.isoformat(),
                    "needs_human": classes[m.id].needs_human if m.id in classes else None,
                    "human_reason": classes[m.id].human_reason if m.id in classes else None,
                    "summary": classes[m.id].summary if m.id in classes else None,
                    "flagged": classes[m.id].flagged if m.id in classes else False,
                }
                for m in messages
            ],
            "pending_reply_ids": [str(p.id) for p in pending],
        }
