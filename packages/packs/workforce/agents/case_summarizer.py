"""Case Summarizer agent: on a filed case, reads the intake text with no identity
and no tools (quarantined reader, so an instruction hidden in the text cannot
steer the system), writes a neutral structured summary and a suggested process
that cites company policy, and moves the case to `process_suggested`.

Suggests only. A human mediator decides every outcome and closes the case (R3).
"""

from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select

from kernel.ai import AgentContext, load_prompt
from kernel.ai.graphs import AgentState, agent_node
from kernel.db import utcnow
from kernel.explain import DecisionDraft
from packs.workforce.models import Case, CaseEvent, ResolutionPlan
from packs.workforce.service import NOT_CONSIDERED

# Deterministic policy mapping: the human-readable process path per case type.
CITATIONS = {
    "workload": ["§4.3", "§6.1"],
    "communication": ["§4.3", "§6.2"],
    "scheduling": ["§4.3", "§6.3"],
}
DEFAULT_CITATIONS = ["§4.1", "§4.2"]


class CaseSummary(BaseModel):
    summary: str = Field(description="Neutral factual summary; no names, no blame.")
    suggested_steps: list[str] = Field(default_factory=list)


@agent_node
def summarize(ctx: AgentContext, state: dict) -> dict:
    case = ctx.session.get(Case, UUID(state["event"]["case_id"]))
    if case is None or case.status != "opened":
        return {}
    intake = ctx.session.scalar(
        select(CaseEvent).where(CaseEvent.case_id == case.id, CaseEvent.kind == "intake")
    )
    if intake is None:
        return {}

    prompt = load_prompt(__file__, "case_summarizer")
    result = ctx.read_untrusted(
        intake.data.get("text", ""), prompt, CaseSummary, "case", str(case.id)
    )
    summary = result.data
    citations = CITATIONS.get(case.case_type, DEFAULT_CITATIONS)

    ctx.session.add(
        CaseEvent(
            tenant_id=ctx.tenant_id,
            case_id=case.id,
            kind="summary",
            at=utcnow(),
            data={"summary": summary.summary, "suggested_steps": summary.suggested_steps},
        )
    )
    ctx.session.add(
        ResolutionPlan(
            tenant_id=ctx.tenant_id,
            case_id=case.id,
            steps=summary.suggested_steps,
            policy_citations=citations,
            status="suggested",
        )
    )
    case.status = "process_suggested"

    ctx.record_decision(
        DecisionDraft(
            kind="workforce.case",
            question=f"Suggested process for case {case.external_id}",
            subject={"case": case.external_id, "type": case.case_type},
            outcome={"status": "process_suggested", "citations": citations},
            rationale=summary.summary,
            not_considered=NOT_CONSIDERED,
            view_roles=["admin", "hr"],
        )
    )
    return {}


def build() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("summarize", summarize)
    graph.add_edge(START, "summarize")
    graph.add_edge("summarize", END)
    return graph
