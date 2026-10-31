"""Employee questions API. Everyone may ask, and answers are limited to what they may read."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from kernel.authz import require_role
from kernel.errors import NotFound
from kernel.events import publish
from kernel.knowledge import QuestionAsked
from kernel.knowledge.models import Question, Ticket
from kernel.web import request_context

HR_ROLES = {"admin", "hr"}

router = APIRouter(prefix="/knowledge", tags=["employee questions"])


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


def _question_json(question: Question) -> dict[str, Any]:
    return {
        "id": str(question.id),
        "text": question.text,
        "status": question.status,
        "answer": question.answer,
        "citations": question.citations,
        "refusal_reason": question.refusal_reason,
        "asked_at": question.created_at.isoformat(),
    }


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


@router.get("/questions/{question_id}", summary="One of your questions")
def get_question(question_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        question = ctx.session.get(Question, question_id)
        if question is None or question.asker_id != ctx.actor.user_id:
            raise NotFound("Question not found")
        return _question_json(question)


@router.get("/tickets", summary="Questions passed to HR")
def list_tickets(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, HR_ROLES)
        rows = ctx.session.execute(
            select(Ticket, Question)
            .join(Question, Question.id == Ticket.question_id)
            .where(Ticket.status == "open")
            .order_by(Ticket.created_at.desc())
        ).all()
        return [
            {
                "id": str(ticket.id),
                "reason": ticket.reason,
                "question": question.text,
                "asked_at": question.created_at.isoformat(),
            }
            for ticket, question in rows
        ]
