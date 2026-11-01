"""Training Planner: a confirmed gap -> an ordered recommendation + a mentor option."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from kernel.ai import AgentContext
from kernel.events.models import EventOutbox
from kernel.explain import DecisionDraft
from kernel.explain import Evidence as DecisionEvidence
from kernel.people.models import Employee, PersonSkillEvidence, Skill
from packs.journey import events as _events  # noqa: F401 - registers the pack's events
from packs.journey.models import Course, SkillGap, TrainingRecommendation
from packs.journey.services import gap as gap_math


def run(ctx: AgentContext, event: EventOutbox | None) -> None:
    payload: dict[str, Any] = dict(event.payload) if event else {}
    gap_id = payload.get("gap_id")
    if not gap_id:
        return
    gap = ctx.session.get(SkillGap, UUID(str(gap_id)))
    if gap is None:
        return
    employee = ctx.session.get(Employee, gap.employee_id)
    skill = ctx.session.get(Skill, gap.skill_id)
    if employee is None or skill is None:
        return
    existing = ctx.session.scalar(
        select(TrainingRecommendation).where(
            TrainingRecommendation.gap_id == gap.id,
            TrainingRecommendation.status.in_(("proposed", "assigned", "completed")),
        )
    )
    if existing is not None:
        return
    courses = ctx.session.scalars(select(Course).where(Course.skill_id == gap.skill_id)).all()
    if not courses:
        return
    by_external = {course.external_id: course for course in courses}
    path = gap_math.course_path(
        [
            {
                "course_id": course.external_id,
                "skill_id": str(course.skill_id),
                "level_gained": course.level_gained,
                "hours": course.hours,
                "cost_tnd": course.cost_tnd,
            }
            for course in courses
        ],
        skill_id=str(gap.skill_id),
        required_level=gap.required_level,
        current_level=gap.current_level,
    )
    if not path.items:
        return
    first = by_external.get(str(path.items[0]["course_id"]))
    if first is None:
        return

    holders: list[dict[str, Any]] = []
    evidence_rows = ctx.session.scalars(
        select(PersonSkillEvidence).where(
            PersonSkillEvidence.skill_id == gap.skill_id,
            PersonSkillEvidence.level >= gap.required_level,
        )
    ).all()
    for evidence in evidence_rows:
        holder = ctx.session.scalar(
            select(Employee).where(Employee.person_id == evidence.person_id)
        )
        if holder is not None:
            holders.append({"employee_id": str(holder.id), "level": evidence.level})
    mentors = gap_math.mentor_candidates(
        holders,
        required_level=gap.required_level,
        learner_id=str(employee.id),
        manager_id=str(employee.manager_id) if employee.manager_id else None,
    )
    mentor = ctx.session.get(Employee, UUID(str(mentors[0]["employee_id"]))) if mentors else None

    decision = ctx.record_decision(
        DecisionDraft(
            kind="training_recommendation",
            question=f"How should we close the {skill.name} gap?",
            outcome={
                "course_id": str(first.id),
                "cost_tnd": str(first.cost_tnd),
                "hours": first.hours,
                "kpi_id": str(first.kpi_id),
                "mentor_employee_id": str(mentor.id) if mentor else None,
            },
            subject={"employee_id": str(employee.id), "gap_id": str(gap.id)},
            rationale=(
                "Ordered by level_gained, hours and cost; the first step is "
                f"{first.title}. A human assigns it."
            ),
            evidence=[
                DecisionEvidence(
                    ref=f"gap:{gap.id}",
                    factor_key=None,
                    source_type="skill_gap",
                    source_id=str(gap.id),
                    quote=gap.message,
                )
            ],
            not_considered=["name", "gender", "age", "nationality", "photo"],
            limits=[gap.message, "The KPI effect is a hypothesis until measured."],
            versions={"model": "deterministic", "prompt_hash": "none"},
            view_roles=["admin", "hr", "manager", "employee"],
        )
    )
    recommendation = TrainingRecommendation(
        tenant_id=ctx.tenant_id,
        gap_id=gap.id,
        employee_id=employee.id,
        kind="course",
        course_id=first.id,
        mentor_employee_id=mentor.id if mentor else None,
        rationale=(
            f"{first.title} is the first step; {first.hours}h, {first.cost_tnd} TND. "
            f"A mentor alternative is {mentor.display_name if mentor else 'not available'}."
        ),
        cost_tnd=first.cost_tnd,
        hours=first.hours,
        kpi_id=first.kpi_id,
        expected_effect=first.expected_effect,
        status="proposed",
    )
    ctx.session.add(recommendation)
    ctx.session.flush()
    ctx.propose(
        "journey.training.assign",
        {"recommendation_id": str(recommendation.id)},
        f"Assign {first.title} to close the {skill.name} gap",
        decision.id,
        f"journey-training:{gap.id}",
        target={"type": "employee", "id": str(employee.id)},
    )
