"""Clash Fixer agent: on a new leave request, drafts a human-readable fix for any
same-team clash and proposes the approval (R2) for a manager to decide.

Proposes only, never applies. The clash itself is detected deterministically
(service/clash.py); the model only phrases the suggestion, and if it is
unavailable the deterministic text is used instead.
"""

from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from kernel import trust
from kernel.ai import AgentContext, load_prompt
from kernel.ai.graphs import AgentState, agent_node
from kernel.explain import DecisionDraft
from kernel.people.models import Employee
from packs.workforce.models import LeaveRequest
from packs.workforce.service import NOT_CONSIDERED

VIEW_ROLES = ["admin", "hr", "manager", "employee", "auditor"]


class FixSuggestion(BaseModel):
    suggestion: str


def _suggestion(ctx: AgentContext, leave: LeaveRequest) -> str:
    base = (
        f"This request overlaps same-team leave {', '.join(leave.clash_of)}. "
        "Consider moving one of the dates or arranging coverage before approving."
    )
    try:
        prompt = load_prompt(__file__, "clash_fixer")
        facts = (
            f"Leave {leave.external_id} from {leave.start_date} to {leave.end_date} "
            f"overlaps same-team requests {leave.clash_of}."
        )
        result = ctx.llm("fast", prompt, facts, FixSuggestion)
        return result.suggestion.strip() or base
    except Exception:  # noqa: BLE001 - the model is optional; fall back to the deterministic text
        return base


@agent_node
def propose_approval(ctx: AgentContext, state: dict) -> dict:
    leave = ctx.session.get(LeaveRequest, UUID(state["event"]["leave_request_id"]))
    if leave is None or leave.status == "approved":
        return {}
    if leave.clash_of:
        rationale = _suggestion(ctx, leave)
        trust.log_action(
            ctx.session,
            ctx.tenant_id,
            "workforce.leave.fix.draft",
            "agent",
            "workforce.clash_fixer",
            data={"leave_request_id": str(leave.id), "clash_of": leave.clash_of},
        )
    else:
        rationale = "No same-team clash found. A manager still approves every request."

    decision = ctx.record_decision(
        DecisionDraft(
            kind="workforce.leave",
            question=f"Approve leave {leave.external_id}?",
            subject={"leave_request_id": str(leave.id)},
            outcome={"status": leave.status, "clash_of": leave.clash_of or []},
            rationale=rationale,
            not_considered=NOT_CONSIDERED,
            view_roles=VIEW_ROLES,
        )
    )
    employee = ctx.session.get(Employee, leave.employee_id)
    ctx.propose(
        "workforce.leave.approve",
        {"leave_request_id": str(leave.id)},
        f"Approve leave {leave.external_id}",
        decision.id,
        f"leave-approve:{leave.id}",
        target={"org_unit": str(employee.org_unit_id)},
    )
    return {}


def build() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("propose_approval", propose_approval)
    graph.add_edge(START, "propose_approval")
    graph.add_edge("propose_approval", END)
    return graph
