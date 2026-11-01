"""Policy answers agent: retrieve -> answer -> check citations. Refuses rather than guesses.

It has no way to change anything: it can only answer from documents, or pass the question to HR.
"""

import re
from decimal import Decimal
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from kernel import trust
from kernel.ai import AgentContext, guard, load_prompt
from kernel.ai.graphs import AgentState, agent_node
from kernel.ai.sanitize import sanitize
from kernel.comms import force_human_reason
from kernel.db import utcnow
from kernel.events import publish
from kernel.knowledge import Hit, QuestionEscalated, search
from kernel.knowledge.models import Question, Ticket

MIN_SIMILARITY = Decimal("0.30")
CITATION = re.compile(r"\[(C\d+)\]")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
CITATION_ONLY = re.compile(r"(\s*\[C\d+\])+\s*[.!?]?")


class Cited(BaseModel):
    ref: str
    quote: str


class PolicyAnswer(BaseModel):
    can_answer: bool
    answer: str
    citations: list[Cited]


class State(AgentState, total=False):
    done: bool


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _sentences(answer: str) -> list[str]:
    """Split into sentences. A citation written after the full stop ("... year. [C1]") belongs to
    the sentence before it, not to a sentence of its own."""
    sentences: list[str] = []
    for part in SENTENCE.split(answer.strip()):
        if sentences and CITATION_ONLY.fullmatch(part):
            sentences[-1] = f"{sentences[-1]} {part}"
        else:
            sentences.append(part)
    return sentences


def check_answer(result: PolicyAnswer, hits: dict[str, Hit]) -> str | None:
    """Each sentence must cite a real passage, and each quote must really be in that passage."""
    if not result.answer.strip():
        return "the answer is empty"
    for sentence in _sentences(result.answer):
        refs = CITATION.findall(sentence)
        if not refs:
            return "a sentence has no citation"
        if any(ref not in hits for ref in refs):
            return "a citation points at no passage"
    if not result.citations:
        return "no citation was given"
    for item in result.citations:
        hit = hits.get(item.ref)
        if hit is None or _normalize(item.quote) not in _normalize(hit.text):
            return "a quote is not in the cited passage"
    return None


def _refuse(ctx: AgentContext, question: Question, reason: str) -> dict:
    """Say so plainly, and hand the question to a person."""
    question.status = "escalated"
    question.refusal_reason = reason
    question.answered_at = utcnow()
    ticket = Ticket(tenant_id=ctx.tenant_id, question_id=question.id, reason=reason)
    ctx.session.add(ticket)
    ctx.session.flush()
    publish(
        ctx.session,
        ctx.tenant_id,
        QuestionEscalated(question_id=question.id, ticket_id=ticket.id),
    )
    return {"done": True}


@agent_node
def answer_question(ctx: AgentContext, state: dict) -> dict:
    session = ctx.session
    question = session.get(Question, UUID(state["event"]["question_id"]))
    if question.status != "pending":
        return {"done": True}
    cleaned = sanitize(question.text).text
    if guard.scan(cleaned).flagged:
        return _refuse(ctx, question, "This question couldn't be answered automatically.")
    sensitive = force_human_reason(cleaned)
    if sensitive:
        return _refuse(ctx, question, f"This is for a person in HR: {sensitive.lower()}.")

    hits = search(session, cleaned, question.asker_roles)
    best = max((hit.similarity for hit in hits), default=Decimal(0))
    question.top_similarity = float(best)
    if not hits or best < MIN_SIMILARITY:
        return _refuse(ctx, question, "No company document covers this.")

    references = {f"C{index}": hit for index, hit in enumerate(hits, start=1)}
    passages = "\n\n".join(
        f"[{ref}] {hit.document_title}, section {hit.section}:\n{hit.text}"
        for ref, hit in references.items()
    )
    prompt = load_prompt(__file__, "policy_answer")
    result = ctx.llm(
        "standard", prompt, f"Question: {cleaned}\n\nPassages:\n{passages}", PolicyAnswer
    )
    if not result.can_answer:
        return _refuse(ctx, question, "The company documents don't answer this clearly.")
    problem = check_answer(result, references)
    if problem:
        return _refuse(ctx, question, f"The answer couldn't be verified: {problem}.")

    used = {ref for ref in CITATION.findall(result.answer)}
    question.status = "answered"
    question.answer = result.answer
    question.citations = [
        {
            **references[ref].as_json(ref),
            "quote": next((c.quote for c in result.citations if c.ref == ref), ""),
        }
        for ref in sorted(used)
    ]
    question.answered_at = utcnow()
    trust.log_action(
        session,
        ctx.tenant_id,
        "kernel.question.answer",
        "agent",
        "kernel.policy_answers",
        prompt_hash=prompt.hash,
        data={"question_id": str(question.id), "citations": sorted(used)},
    )
    return {"done": True}


def build() -> StateGraph:
    graph = StateGraph(State)
    graph.add_node("answer_question", answer_question)
    graph.add_edge(START, "answer_question")
    graph.add_edge("answer_question", END)
    return graph
