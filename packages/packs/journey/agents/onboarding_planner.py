"""Onboarding Planner: turns a hire event into a draft 30/60/90 proposal.

Deterministic plan structure, no LLM arithmetic. The run ends at a proposal;
only the executor applies it after a human approves the payload hash.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select

from kernel.ai import AgentContext
from kernel.events.models import EventOutbox
from kernel.explain import DecisionDraft, Evidence
from kernel.people.models import Employee
from packs.journey import events as _events  # noqa: F401 - registers the pack's events
from packs.journey.models import (
    OnboardingPlan,
    OnboardingTask,
    OnboardingTemplate,
    TemplateTask,
)
from packs.journey.services import planning


def _payload(event: EventOutbox | None) -> dict[str, Any]:
    if event is None:
        return {}
    return dict(event.payload)


def run(ctx: AgentContext, event: EventOutbox | None) -> None:
    payload = _payload(event)
    employee_external = payload.get("employee_id")
    if not employee_external:
        return
    employee = ctx.session.scalar(
        select(Employee).where(Employee.external_id == str(employee_external))
    )
    if employee is None:
        return
    start = (
        date.fromisoformat(str(payload["start_date"]))
        if payload.get("start_date")
        else employee.start_date
    )
    existing = ctx.session.scalar(
        select(OnboardingPlan).where(
            OnboardingPlan.employee_id == employee.id,
            OnboardingPlan.start_date == start,
        )
    )
    if existing is not None:
        return
    template = ctx.session.scalar(
        select(OnboardingTemplate)
        .where(
            OnboardingTemplate.position_id == employee.position_id,
            OnboardingTemplate.status == "active",
        )
        .order_by(OnboardingTemplate.version.desc())
    )
    if template is None:
        return
    template_tasks = ctx.session.scalars(
        select(TemplateTask)
        .where(TemplateTask.template_id == template.id)
        .order_by(TemplateTask.position)
    ).all()
    if not template_tasks:
        return

    plan = OnboardingPlan(
        tenant_id=ctx.tenant_id,
        employee_id=employee.id,
        template_id=template.id,
        start_date=start,
        target_ramp_date=planning.due_at(start, 90).date(),
        status="draft",
        phase="preboarding",
    )
    ctx.session.add(plan)
    ctx.session.flush()

    tasks_payload: list[dict[str, Any]] = []
    for item in template_tasks:
        owner_employee_id = None
        if item.owner_role == "manager":
            owner_employee_id = employee.manager_id
        elif item.owner_role == "employee":
            owner_employee_id = employee.id
        due_at = planning.due_at(start, item.due_day)
        ctx.session.add(
            OnboardingTask(
                tenant_id=ctx.tenant_id,
                plan_id=plan.id,
                template_task_id=item.id,
                phase=item.phase,
                position=item.position,
                title=item.title,
                task_kind=item.task_kind,
                owner_role=item.owner_role,
                owner_employee_id=owner_employee_id,
                due_at=due_at,
                status="pending",
                mandatory=item.mandatory,
                evidence_required=item.evidence_required,
            )
        )
        tasks_payload.append(
            {
                "position": item.position,
                "phase": item.phase,
                "title": item.title,
                "task_kind": item.task_kind,
                "owner_role": item.owner_role,
                "owner_employee_id": str(owner_employee_id) if owner_employee_id else None,
                "due_at": due_at.isoformat(),
                "mandatory": item.mandatory,
                "evidence_required": item.evidence_required,
            }
        )

    evidence = [
        Evidence(
            ref=f"pos-{str(employee.position_id)[:8]}",
            factor_key=None,
            source_type="role_profile",
            source_id=str(employee.position_id),
            quote="Role profile v1 and the approved onboarding template",
        )
    ]
    for gap in payload.get("hired_gaps", []):
        skill_id = gap.get("skill_id")
        if skill_id:
            evidence.append(
                Evidence(
                    ref=f"gap-{str(skill_id)[:8]}",
                    factor_key=None,
                    source_type="hiring_gap",
                    source_id=str(skill_id),
                    quote=str(gap.get("evidence", "Screening gap inherited at hire")),
                )
            )
    decision = ctx.record_decision(
        DecisionDraft(
            kind="onboarding_plan",
            question="Should we activate this 30/60/90 plan?",
            outcome={
                "plan_id": str(plan.id),
                "tasks": len(tasks_payload),
                "start_date": start.isoformat(),
            },
            subject={"employee_id": str(employee.id)},
            rationale=(
                "Draft built from the role template and role profile. The plan is a "
                "proposal until a human approves the exact payload."
            ),
            evidence=evidence,
            not_considered=["name", "gender", "age", "nationality", "photo"],
            limits=["A draft only; a human must approve it before tasks become active."],
            versions={"model": "deterministic", "prompt_hash": "none"},
            view_roles=["admin", "hr", "manager", "employee"],
        )
    )
    ctx.propose(
        "journey.plan.activate",
        {
            "plan_id": str(plan.id),
            "tasks": tasks_payload,
            "buddy_id": None,
        },
        f"Activate the 30/60/90 plan for {employee.display_name}",
        decision.id,
        f"journey-plan:{employee.id}:{start.isoformat()}",
        target={"type": "employee", "id": str(employee.id)},
    )

