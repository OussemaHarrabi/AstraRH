"""Effects of approved internal journey actions.

The worker calls these only after the trust gate has passed. An external action
(email) stays in the executor; these are the internal writes.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel.db import utcnow
from kernel.events import publish
from packs.journey.events import PlanActivated, SkillGapConfirmed, TrainingCompleted
from packs.journey.models import (
    BuddyAssignment,
    Enrollment,
    OnboardingPlan,
    OnboardingTask,
    SkillGap,
    TrainingRecommendation,
)


def _uuid(value: Any) -> UUID | None:
    return UUID(str(value)) if value else None


def activate_plan(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    plan = session.get(OnboardingPlan, UUID(str(payload["plan_id"])), with_for_update=True)
    if plan is None:
        raise ValueError("plan not found")
    for item in payload.get("tasks", []):
        position = int(item["position"])
        task = session.scalar(
            select(OnboardingTask).where(
                OnboardingTask.plan_id == plan.id,
                OnboardingTask.position == position,
            )
        )
        if task is None:
            task = OnboardingTask(
                tenant_id=tenant_id,
                plan_id=plan.id,
                position=position,
                status="pending",
            )
            session.add(task)
        task.phase = str(item.get("phase", "week1"))
        task.title = str(item.get("title", "Onboarding task"))
        task.task_kind = str(item.get("task_kind", "standard"))
        task.owner_role = str(item.get("owner_role", "employee"))
        task.owner_employee_id = _uuid(item.get("owner_employee_id"))
        if item.get("due_at"):
            task.due_at = datetime.fromisoformat(str(item["due_at"]))
        task.mandatory = bool(item.get("mandatory", False))
        task.evidence_required = str(item.get("evidence_required", "Evidence"))
    buddy_id = _uuid(payload.get("buddy_id"))
    if buddy_id is not None:
        buddy = session.scalar(
            select(BuddyAssignment).where(BuddyAssignment.plan_id == plan.id)
        )
        if buddy is None:
            buddy = BuddyAssignment(tenant_id=tenant_id, plan_id=plan.id)
            session.add(buddy)
        buddy.buddy_employee_id = buddy_id
        buddy.cadence = str(payload.get("buddy_cadence", "weekly"))
        buddy.approval_id = _uuid(payload.get("approval_id"))
    plan.status = "in_progress"
    plan.phase = payload.get("phase", plan.phase)
    plan.approval_id = _uuid(payload.get("approval_id"))
    session.flush()
    publish(
        session,
        tenant_id,
        PlanActivated(plan_id=plan.id, employee_id=plan.employee_id),
    )
    return f"plan_activated:{plan.id}"


def assign_buddy(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    plan_id = UUID(str(payload["plan_id"]))
    buddy = session.scalar(
        select(BuddyAssignment).where(BuddyAssignment.plan_id == plan_id).with_for_update()
    )
    if buddy is None:
        buddy = BuddyAssignment(tenant_id=tenant_id, plan_id=plan_id)
        session.add(buddy)
    buddy.buddy_employee_id = UUID(str(payload["buddy_employee_id"]))
    buddy.cadence = payload.get("cadence", "weekly")
    buddy.approval_id = _uuid(payload.get("approval_id"))
    buddy.approved_by = _uuid(payload.get("approved_by"))
    session.flush()
    return f"buddy_assigned:{buddy.id}"


def reassign_task(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    task = session.get(OnboardingTask, UUID(str(payload["task_id"])), with_for_update=True)
    if task is None:
        raise ValueError("task not found")
    task.owner_employee_id = _uuid(payload.get("owner_employee_id"))
    return f"task_reassigned:{task.id}"


def confirm_gap(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    gap = session.get(SkillGap, UUID(str(payload["gap_id"])), with_for_update=True)
    if gap is None:
        raise ValueError("gap not found")
    gap.status = "confirmed"
    gap.decided_by = _uuid(payload.get("decided_by"))
    gap.decided_at = utcnow()
    gap.decision_note = payload.get("decision_note")
    gap.decision_record_id = _uuid(payload.get("decision_record_id"))
    publish(
        session,
        tenant_id,
        SkillGapConfirmed(
            gap_id=gap.id,
            employee_id=gap.employee_id,
            skill_id=gap.skill_id,
            current_level=gap.current_level,
            required_level=gap.required_level,
            gap=gap.gap,
            severity=gap.severity,
        ),
    )
    return f"gap_confirmed:{gap.id}"


def assign_training(
    session: Session, tenant_id: UUID, payload: dict[str, Any], key: str
) -> str:
    recommendation = session.get(
        TrainingRecommendation, UUID(str(payload["recommendation_id"])), with_for_update=True
    )
    if recommendation is None:
        raise ValueError("recommendation not found")
    enrollment = session.scalar(
        select(Enrollment).where(Enrollment.recommendation_id == recommendation.id)
    )
    if enrollment is None:
        enrollment = Enrollment(
            tenant_id=tenant_id,
            recommendation_id=recommendation.id,
            employee_id=recommendation.employee_id,
            course_id=recommendation.course_id,
            status="assigned",
        )
        session.add(enrollment)
    recommendation.status = "assigned"
    recommendation.approval_id = _uuid(payload.get("approval_id"))
    session.flush()
    return f"training_assigned:{enrollment.id}"


def verify_training(
    session: Session, tenant_id: UUID, payload: dict[str, Any], key: str
) -> str:
    enrollment = session.get(
        Enrollment, UUID(str(payload["enrollment_id"])), with_for_update=True
    )
    if enrollment is None:
        raise ValueError("enrollment not found")
    recommendation = session.get(TrainingRecommendation, enrollment.recommendation_id)
    if recommendation is None:
        raise ValueError("recommendation not found")
    gap = session.get(SkillGap, recommendation.gap_id)
    if gap is None:
        raise ValueError("gap not found")

    enrollment.status = "completed"
    enrollment.completed_at = utcnow()
    enrollment.score = (
        Decimal(str(payload["score"])) if payload.get("score") is not None else None
    )
    enrollment.evidence = payload.get("evidence") or {}
    enrollment.verified_by = _uuid(payload.get("verified_by"))
    enrollment.verified_at = utcnow()
    recommendation.status = "completed"

    level = int(payload.get("level", gap.required_level))
    gap.current_level = level
    gap.gap = max(0, gap.required_level - level)
    gap.status = "closed" if gap.gap == 0 else "confirmed"
    gap.decided_by = _uuid(payload.get("verified_by"))
    gap.decided_at = utcnow()
    gap.decision_note = payload.get("decision_note", "Verified after training")

    publish(
        session,
        tenant_id,
        TrainingCompleted(
            enrollment_id=enrollment.id,
            employee_id=enrollment.employee_id,
            course_id=enrollment.course_id,
            cost_tnd=str(recommendation.cost_tnd),
            hours=recommendation.hours,
            kpi_id=recommendation.kpi_id,
            completed_at=enrollment.completed_at,
            verification=payload.get("verification", "assessment"),
            measured_effect=payload.get("measured_effect"),
        ),
    )
    return f"training_verified:{enrollment.id}"

