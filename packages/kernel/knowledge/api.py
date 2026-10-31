"""Employee questions API. Everyone may ask, and answers are limited to what they may read.

HR sees the questions the assistant passed on, claims them, and answers or closes them. HR also
publishes policy documents; indexing runs in the worker, since only it reaches the ml service.
"""

from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from kernel import trust
from kernel.authz import require_role
from kernel.db import utcnow
from kernel.errors import Conflict, NotFound
from kernel.events import publish
from kernel.knowledge import DocumentSubmitted, QuestionAsked, TicketResolved
from kernel.knowledge.models import Chunk, Document, Question, Ticket
from kernel.web import request_context

HR_ROLES = {"admin", "hr"}
TICKET_STATUSES = ("open", "claimed", "answered", "closed")
OPEN_STATUSES = ("open", "claimed")

router = APIRouter(prefix="/knowledge", tags=["employee questions"])


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class FeedbackBody(BaseModel):
    helpful: bool
    comment: str = Field(default="", max_length=1000)


class TicketAnswerBody(BaseModel):
    answer: str = Field(min_length=3, max_length=4000)


class TicketCloseBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class DocumentBody(BaseModel):
    external_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")
    title: str = Field(min_length=1, max_length=200)
    version: str = Field(default="1", min_length=1, max_length=32)
    effective_date: date | None = None
    audience_roles: list[str] = Field(default_factory=list)
    markdown: str = Field(min_length=10, max_length=200_000)


def _question_json(question: Question) -> dict[str, Any]:
    return {
        "id": str(question.id),
        "text": question.text,
        "status": question.status,
        "answer": question.answer,
        "answered_by": "hr" if question.answered_by else ("assistant" if question.answer else None),
        "citations": question.citations,
        "refusal_reason": question.refusal_reason,
        "feedback": (
            None
            if question.feedback_helpful is None
            else {"helpful": question.feedback_helpful, "comment": question.feedback_comment}
        ),
        "asked_at": question.created_at.isoformat(),
        "answered_at": question.answered_at.isoformat() if question.answered_at else None,
    }


def _ticket_json(ticket: Ticket, question: Question, detail: bool = False) -> dict[str, Any]:
    body = {
        "id": str(ticket.id),
        "status": ticket.status,
        "reason": ticket.reason,
        "question_id": str(question.id),
        "question": question.text,
        "asker_id": str(question.asker_id),
        "assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None,
        "asked_at": question.created_at.isoformat(),
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
    }
    if detail:
        body |= {
            "asker_roles": question.asker_roles,
            "answer": ticket.answer,
            "resolved_by": str(ticket.resolved_by) if ticket.resolved_by else None,
            "assistant_answer": question.answer if not question.answered_by else None,
            "assistant_citations": question.citations,
            "top_similarity": question.top_similarity,
            "feedback": _question_json(question)["feedback"],
        }
    return body


def _document_json(document: Document, chunks: int | None = None) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "external_id": document.external_id,
        "title": document.title,
        "version": document.version,
        "effective_date": document.effective_date.isoformat() if document.effective_date else None,
        "audience_roles": document.audience_roles,
        "status": document.status,
        "sections": chunks,
        "published_at": document.created_at.isoformat(),
        "superseded_at": document.superseded_at.isoformat() if document.superseded_at else None,
    }


def _readable(roles: set[str]):
    """Same rule as search: no audience means everyone, otherwise the roles must overlap."""
    return or_(Document.audience_roles == [], Document.audience_roles.overlap(sorted(roles)))


# ----- Asking -----


@router.post("/questions", status_code=202, summary="Ask a question about company policy")
def ask(body: AskBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        question = Question(
            tenant_id=ctx.actor.tenant_id,
            asker_id=ctx.actor.user_id,
            asker_roles=sorted(ctx.actor.roles),
            text=body.question,
        )
        ctx.session.add(question)
        ctx.session.flush()
        publish(ctx.session, ctx.actor.tenant_id, QuestionAsked(question_id=question.id))
        return _question_json(question)


@router.get("/questions", summary="Your recent questions")
def my_questions(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        rows = ctx.session.scalars(
            select(Question)
            .where(Question.asker_id == ctx.actor.user_id)
            .order_by(Question.created_at.desc())
            .limit(20)
        )
        return [_question_json(row) for row in rows]


def _own_question(ctx, question_id: UUID, lock: bool = False) -> Question:
    question = ctx.session.get(Question, question_id, with_for_update=lock)
    if question is None or question.asker_id != ctx.actor.user_id:
        raise NotFound("Question not found")
    return question


@router.get("/questions/{question_id}", summary="One of your questions")
def get_question(question_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        return _question_json(_own_question(ctx, question_id))


@router.post(
    "/questions/{question_id}/feedback",
    summary="Say whether the answer helped. If it didn't, HR gets the question.",
)
def give_feedback(question_id: UUID, body: FeedbackBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        session, tenant = ctx.session, ctx.actor.tenant_id
        question = _own_question(ctx, question_id, lock=True)
        if question.status != "answered":
            raise Conflict("Only an answered question can be rated")
        question.feedback_helpful = body.helpful
        question.feedback_comment = body.comment.strip() or None
        ticket = None
        if not body.helpful:
            ticket = session.scalar(
                select(Ticket).where(
                    Ticket.question_id == question.id, Ticket.status.in_(OPEN_STATUSES)
                )
            )
            if ticket is None:
                reason = "The employee said the answer didn't help"
                if question.feedback_comment:
                    reason += f": {question.feedback_comment}"
                ticket = Ticket(tenant_id=tenant, question_id=question.id, reason=reason)
                session.add(ticket)
                session.flush()
        trust.log_action(
            session,
            tenant,
            "kernel.question.feedback",
            "human",
            str(ctx.actor.user_id),
            data={"question_id": str(question.id), "helpful": body.helpful},
        )
        return _question_json(question) | {"ticket_id": str(ticket.id) if ticket else None}


# ----- HR: passed-on questions -----


@router.get("/tickets", summary="Questions passed to HR")
def list_tickets(
    request: Request,
    status: Literal["open", "claimed", "answered", "closed", "active", "all"] = "active",
    mine: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """`active` means open or claimed, which is the HR work queue."""
    with request_context(request) as ctx:
        require_role(ctx.actor, HR_ROLES)
        query = select(Ticket, Question).join(Question, Question.id == Ticket.question_id)
        if status == "active":
            query = query.where(Ticket.status.in_(OPEN_STATUSES))
        elif status != "all":
            query = query.where(Ticket.status == status)
        if mine:
            query = query.where(Ticket.assignee_id == ctx.actor.user_id)
        rows = ctx.session.execute(query.order_by(Ticket.created_at.asc()).limit(limit)).all()
        return [_ticket_json(ticket, question) for ticket, question in rows]


def _ticket(ctx, ticket_id: UUID, lock: bool = False) -> tuple[Ticket, Question]:
    require_role(ctx.actor, HR_ROLES)
    ticket = ctx.session.get(Ticket, ticket_id, with_for_update=lock)
    if ticket is None:
        raise NotFound("Ticket not found")
    return ticket, ctx.session.get(Question, ticket.question_id, with_for_update=lock)


@router.get("/tickets/{ticket_id}", summary="One passed-on question, with what the assistant found")
def get_ticket(ticket_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        ticket, question = _ticket(ctx, ticket_id)
        return _ticket_json(ticket, question, detail=True)


@router.post("/tickets/{ticket_id}/claim", summary="Take this question, so others know")
def claim_ticket(ticket_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        ticket, question = _ticket(ctx, ticket_id, lock=True)
        if ticket.status not in OPEN_STATUSES:
            raise Conflict(f"This ticket is already {ticket.status}")
        if ticket.assignee_id not in (None, ctx.actor.user_id):
            raise Conflict("Someone else has claimed this ticket")
        ticket.assignee_id = ctx.actor.user_id
        ticket.status = "claimed"
        return _ticket_json(ticket, question, detail=True)


@router.post("/tickets/{ticket_id}/release", summary="Give the question back to the queue")
def release_ticket(ticket_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        ticket, question = _ticket(ctx, ticket_id, lock=True)
        if ticket.status != "claimed":
            raise Conflict(f"This ticket is {ticket.status}, not claimed")
        ticket.assignee_id = None
        ticket.status = "open"
        return _ticket_json(ticket, question, detail=True)


def _resolve(ctx, ticket: Ticket, question: Question, outcome: str, action: str) -> None:
    now = utcnow()
    ticket.status = outcome
    ticket.resolved_by = ctx.actor.user_id
    ticket.resolved_at = now
    ticket.assignee_id = ticket.assignee_id or ctx.actor.user_id
    publish(
        ctx.session,
        ctx.actor.tenant_id,
        TicketResolved(ticket_id=ticket.id, question_id=question.id, outcome=outcome),
    )
    trust.log_action(
        ctx.session,
        ctx.actor.tenant_id,
        action,
        "human",
        str(ctx.actor.user_id),
        data={"ticket_id": str(ticket.id), "question_id": str(question.id)},
    )


@router.post("/tickets/{ticket_id}/answer", summary="Answer the employee yourself")
def answer_ticket(ticket_id: UUID, body: TicketAnswerBody, request: Request) -> dict[str, Any]:
    """The employee sees this as an answer from HR, never as one from the assistant."""
    with request_context(request) as ctx:
        ticket, question = _ticket(ctx, ticket_id, lock=True)
        if ticket.status not in OPEN_STATUSES:
            raise Conflict(f"This ticket is already {ticket.status}")
        if ticket.assignee_id not in (None, ctx.actor.user_id):
            raise Conflict("Someone else has claimed this ticket")
        ticket.answer = body.answer.strip()
        question.status = "answered"
        question.answer = ticket.answer
        question.citations = []
        question.answered_by = ctx.actor.user_id
        question.answered_at = utcnow()
        question.feedback_helpful = None
        question.feedback_comment = None
        _resolve(ctx, ticket, question, "answered", "kernel.ticket.answer")
        return _ticket_json(ticket, question, detail=True)


@router.post("/tickets/{ticket_id}/close", summary="Close a question that needs no answer")
def close_ticket(ticket_id: UUID, body: TicketCloseBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        ticket, question = _ticket(ctx, ticket_id, lock=True)
        if ticket.status not in OPEN_STATUSES:
            raise Conflict(f"This ticket is already {ticket.status}")
        ticket.answer = None
        ticket.reason = f"{ticket.reason} | Closed: {body.reason.strip()}"
        if question.status == "escalated":
            question.status = "closed"
        _resolve(ctx, ticket, question, "closed", "kernel.ticket.close")
        return _ticket_json(ticket, question, detail=True)


@router.get("/stats", summary="How the assistant is doing: answered, passed on, rated")
def stats(request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, HR_ROLES)
        session = ctx.session
        by_status = dict(
            session.execute(select(Question.status, func.count()).group_by(Question.status)).all()
        )
        tickets = dict(
            session.execute(select(Ticket.status, func.count()).group_by(Ticket.status)).all()
        )
        rated = dict(
            session.execute(
                select(Question.feedback_helpful, func.count())
                .where(Question.feedback_helpful.is_not(None))
                .group_by(Question.feedback_helpful)
            ).all()
        )
        by_hr = session.scalar(
            select(func.count()).select_from(Question).where(Question.answered_by.is_not(None))
        )
        total = sum(by_status.values())
        answered = by_status.get("answered", 0)
        return {
            "questions": total,
            "by_status": by_status,
            "answered_by_assistant": answered - (by_hr or 0),
            "answered_by_hr": by_hr or 0,
            "tickets": tickets,
            "helpful": rated.get(True, 0),
            "not_helpful": rated.get(False, 0),
        }


# ----- Policy documents -----


@router.get("/documents", summary="Policy documents you may read")
def list_documents(request: Request, include_superseded: bool = False) -> list[dict[str, Any]]:
    """HR also sees documents still being indexed, and older versions when asked."""
    with request_context(request) as ctx:
        is_hr = bool(HR_ROLES & set(ctx.actor.roles))
        sections = (
            select(Chunk.document_id, func.count().label("n"))
            .group_by(Chunk.document_id)
            .subquery()
        )
        query = select(Document, sections.c.n).outerjoin(
            sections, sections.c.document_id == Document.id
        )
        if not is_hr:
            query = query.where(_readable(set(ctx.actor.roles)), Document.status == "active")
        elif not include_superseded:
            query = query.where(Document.status != "superseded")
        rows = ctx.session.execute(query.order_by(Document.title, Document.created_at.desc())).all()
        return [_document_json(document, n or 0) for document, n in rows]


@router.get("/documents/{document_id}", summary="One policy document, section by section")
def get_document(document_id: UUID, request: Request) -> dict[str, Any]:
    """What a citation points at. Same permission rule as search."""
    with request_context(request) as ctx:
        is_hr = bool(HR_ROLES & set(ctx.actor.roles))
        query = select(Document).where(Document.id == document_id)
        if not is_hr:
            query = query.where(_readable(set(ctx.actor.roles)))
        document = ctx.session.scalar(query)
        if document is None:
            raise NotFound("Document not found")
        chunks = ctx.session.scalars(
            select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.position)
        ).all()
        return _document_json(document, len(chunks)) | {
            "content": [
                {"chunk_id": str(chunk.id), "section": chunk.section, "text": chunk.text}
                for chunk in chunks
            ]
        }


@router.post(
    "/documents",
    status_code=202,
    summary="Publish a policy, or a new version of one. The older version stops being cited.",
)
def publish_document(body: DocumentBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, HR_ROLES)
        session, tenant = ctx.session, ctx.actor.tenant_id
        clash = session.scalar(
            select(Document.id).where(
                Document.external_id == body.external_id,
                Document.version == body.version,
                Document.status != "failed",
            )
        )
        if clash:
            raise Conflict(f"Version {body.version} of {body.external_id} already exists")
        document = Document(
            tenant_id=tenant,
            external_id=body.external_id,
            title=body.title,
            version=body.version,
            effective_date=body.effective_date,
            audience_roles=sorted(set(body.audience_roles)),
            status="processing",
            source=body.markdown,
            uploaded_by=ctx.actor.user_id,
        )
        session.add(document)
        session.flush()
        publish(session, tenant, DocumentSubmitted(document_id=document.id))
        trust.log_action(
            session,
            tenant,
            "kernel.document.publish",
            "human",
            str(ctx.actor.user_id),
            data={
                "document_id": str(document.id),
                "external_id": body.external_id,
                "version": body.version,
            },
        )
        return _document_json(document, 0)
