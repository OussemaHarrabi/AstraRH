"""Rubric Builder agent: drafts criteria from a job offer. A recruiter edits and activates them."""

from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from kernel import trust
from kernel.ai import AgentContext, load_prompt
from kernel.ai.graphs import AgentState, agent_node
from packs.talent.models import Job, Rubric


class DraftCriterion(BaseModel):
    id: str
    label: str
    description: str
    weight_percent: int
    must_have: bool
    required_years: int
    keywords: list[str] = Field(default_factory=list)


class RubricDraft(BaseModel):
    criteria: list[DraftCriterion]


def normalized_weights(percents: list[int]) -> list[str]:
    """Scale to exact two-decimal weights that sum to exactly 1, by largest remainder."""
    safe = [max(1, p) for p in percents]
    total = Decimal(sum(safe))
    exact = [Decimal(p) / total for p in safe]
    floored = [w.quantize(Decimal("0.01"), rounding=ROUND_DOWN) for w in exact]
    short = int((Decimal(1) - sum(floored)) / Decimal("0.01"))
    order = sorted(range(len(safe)), key=lambda i: exact[i] - floored[i], reverse=True)
    for index in order[:short]:
        floored[index] += Decimal("0.01")
    return [str(w) for w in floored]


@agent_node
def draft_rubric(ctx: AgentContext, state: dict) -> dict:
    job = ctx.session.get(Job, UUID(state["event"]["job_id"]))
    existing = ctx.session.scalar(
        select(func.count()).select_from(Rubric).where(Rubric.job_id == job.id)
    )
    if existing:
        return {}
    prompt = load_prompt(__file__, "rubric_builder")
    result = ctx.read_untrusted(
        f"{job.title}\n\n{job.description}",
        prompt,
        RubricDraft,
        "job_offer",
        str(job.id),
        tier="fast",
    )
    weights = normalized_weights([c.weight_percent for c in result.data.criteria])
    ctx.session.add(
        Rubric(
            tenant_id=ctx.tenant_id,
            job_id=job.id,
            version=1,
            status="draft",
            source="agent",
            criteria=[
                {
                    "id": c.id,
                    "label": c.label,
                    "description": c.description,
                    "weight": weight,
                    "must_have": c.must_have,
                    "required_years": c.required_years,
                    "keywords": [k.lower() for k in c.keywords],
                }
                for c, weight in zip(result.data.criteria, weights, strict=True)
            ],
        )
    )
    trust.log_action(
        ctx.session,
        ctx.tenant_id,
        "talent.rubric.draft",
        "agent",
        "talent.rubric_builder",
        prompt_hash=prompt.hash,
        data={"job_id": str(job.id)},
    )
    return {}


def build() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("draft_rubric", draft_rubric)
    graph.add_edge(START, "draft_rubric")
    graph.add_edge("draft_rubric", END)
    return graph
