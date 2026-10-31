"""Inbox Triage agent: classify one inbound message through the quarantined reader."""

from typing import Literal
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from sqlalchemy import select

from kernel import trust
from kernel.ai import AgentContext, EvidenceSpan, load_prompt
from kernel.ai.graphs import AgentState, agent_node
from kernel.comms import MessageClassified, force_human_reason
from kernel.comms.models import Classification, Message
from kernel.events import publish

MessageType = Literal[
    "application",
    "availability",
    "reschedule",
    "question",
    "offer_or_salary",
    "legal_or_complaint",
    "visa_or_permit",
    "policy_question",
    "internal",
    "spam",
    "other",
]
FLAG_REASON = "This message tries to instruct the AI"


class Triage(BaseModel):
    type: MessageType
    urgency: Literal["high", "normal", "low"]
    needs_human: bool
    human_reason: str | None
    summary: str
    evidence: EvidenceSpan


@agent_node
def classify(ctx: AgentContext, state: dict) -> dict:
    message = ctx.session.get(Message, UUID(state["event"]["message_id"]))
    done = ctx.session.scalar(
        select(Classification.id).where(Classification.message_id == message.id)
    )
    if done:
        return {}
    prompt = load_prompt(__file__, "triage")
    result = ctx.read_untrusted(
        f"Subject: {message.subject}\n\n{message.body}",
        prompt,
        Triage,
        "email",
        str(message.id),
        tier="fast",
    )
    triage = result.data
    # Code can only add a flag. Sensitive topics and injection attempts always reach a person.
    forced = force_human_reason(f"{message.subject}\n{message.body}")
    reason = triage.human_reason if triage.needs_human else None
    if forced:
        reason = forced
    if result.flagged:
        reason = FLAG_REASON
    needs_human = triage.needs_human or bool(forced) or result.flagged
    ctx.session.add(
        Classification(
            tenant_id=ctx.tenant_id,
            message_id=message.id,
            type=triage.type,
            urgency="high" if forced and triage.urgency == "low" else triage.urgency,
            needs_human=needs_human,
            human_reason=reason or ("Flagged for review" if needs_human else None),
            summary=triage.summary[:400],
            quote=triage.evidence.quote or None,
            flagged=result.flagged,
            flags=sorted({*result.reasons, *result.findings}),
        )
    )
    ctx.session.flush()
    trust.log_action(
        ctx.session,
        ctx.tenant_id,
        "kernel.email.classify",
        "agent",
        "kernel.inbox_triage",
        prompt_hash=prompt.hash,
        data={"message_id": str(message.id), "type": triage.type, "needs_human": needs_human},
    )
    publish(
        ctx.session,
        ctx.tenant_id,
        MessageClassified(
            message_id=message.id,
            thread_id=message.thread_id,
            type=triage.type,
            urgency=triage.urgency,
            needs_human=needs_human,
        ),
    )
    return {}


def build_triage() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("classify", classify)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", END)
    return graph
