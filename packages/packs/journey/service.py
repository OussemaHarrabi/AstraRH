"""Journey operations shared by the HTTP API, the seed loader and the handlers."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kernel import trust
from kernel.db import utcnow
from kernel.errors import Conflict, NotFound
from kernel.events import publish
from kernel.identity.models import UserAccount
from kernel.people.models import Employee
from packs.journey.events import EvidenceRecorded, PulseSubmitted
from packs.journey.models import (
    Checkin,
    OnboardingPlan,
    OnboardingTask,
    PulseResponse,
    PulseSurvey,
    SkillGap,
)
from packs.journey.services import planning

ADMIN_ROLES = {"admin", "hr", "auditor"}
MANAGER_ROLE = "manager"
EMPLOYEE_ROLE = "employee"


def employee_for_actor(session: Session, actor) -> Employee | None:
    user = session.get(UserAccount, actor.user_id)
    if user is None or user.person_id is None:
        return None
    return session.scalar(select(Employee).where(Employee.person_id == user.person_id))


def can_view_plan(session: Session, actor, plan: OnboardingPlan) -> bool:
    roles = actor.roles
    if roles & ADMIN_ROLES:
        return True
    employee = employee_for_actor(session, actor)
    if employee is None:
        return False
    if plan.employee_id == employee.id:
        return True
    if MANAGER_ROLE in roles:
        owner = session.get(Employee, plan.employee_id)
        return owner is not None and owner.manager_id == employee.id
    return False


def plans_for_actor(session: Session, actor) -> list[OnboardingPlan]:
    statement = select(OnboardingPlan).order_by(OnboardingPlan.start_date.desc())
    if actor.roles & ADMIN_ROLES:
        return list(session.scalars(statement).all())
    employee = employee_for_actor(session, actor)
    if employee is None:
        return []
    employee_ids = {employee.id}
    if MANAGER_ROLE in actor.roles:
        employee_ids.update(
            session.scalars(select(Employee.id).where(Employee.manager_id == employee.id)).all()
        )
    statement = statement.where(OnboardingPlan.employee_id.in_(employee_ids))
    return list(session.scalars(statement).all())


def plan_for_actor(session: Session, actor, plan_id: UUID) -> OnboardingPlan:
    plan = session.get(OnboardingPlan, plan_id)
    if plan is None or not can_view_plan(session, actor, plan):
        raise NotFound("Plan not found")
    return plan


def submit_checkin(
    session: Session,
    tenant_id: UUID,
    plan_id: UUID,
    checkin_id: UUID,
    answers: dict[str, Any],
    actor,
) -> Checkin:
    plan = plan_for_actor(session, actor, plan_id)
    checkin = session.get(Checkin, checkin_id, with_for_update=True)
    if checkin is None or checkin.plan_id != plan.id:
        raise NotFound("Check-in not found")
    if checkin.status == "completed":
        raise Conflict("This check-in was already submitted")
    survey = session.scalar(select(PulseSurvey).where(PulseSurvey.checkin_id == checkin.id))
    if survey is None:
        survey = PulseSurvey(tenant_id=tenant_id, checkin_id=checkin.id, version=1, questions=[])
        session.add(survey)
        session.flush()
    if session.scalar(select(PulseResponse).where(PulseResponse.checkin_id == checkin.id)):
        raise Conflict("A response already exists")
    session.add(
        PulseResponse(
            tenant_id=tenant_id,
            survey_id=survey.id,
            checkin_id=checkin.id,
            answers=answers,
            submitted_at=utcnow(),
        )
    )
    checkin.status = "completed"
    checkin.completed_at = utcnow()
    trust.log_action(
        session,
        tenant_id,
        "journey.checkin.submit",
        "human",
        str(actor.user_id),
        checkin_id=str(checkin.id),
        plan_id=str(plan.id),
    )
    publish(
        session,
        tenant_id,
        PulseSubmitted(
            checkin_id=checkin.id,
            plan_id=plan.id,
            employee_id=plan.employee_id,
            answers=answers,
        ),
    )
    return checkin


def complete_task(
    session: Session,
    tenant_id: UUID,
    plan_id: UUID,
    task_id: UUID,
    evidence: dict[str, Any],
    actor,
) -> OnboardingTask:
    plan = plan_for_actor(session, actor, plan_id)
    task = session.get(OnboardingTask, task_id, with_for_update=True)
    if task is None or task.plan_id != plan.id:
        raise NotFound("Task not found")
    if task.status == "completed":
        return task
    task.status = "completed"
    task.evidence = evidence
    task.completed_at = utcnow()
    trust.log_action(
        session,
        tenant_id,
        "journey.task.complete",
        "human",
        str(actor.user_id),
        task_id=str(task.id),
        plan_id=str(plan.id),
    )
    publish(
        session,
        tenant_id,
        EvidenceRecorded(
            task_id=task.id,
            plan_id=plan.id,
            employee_id=plan.employee_id,
            summary=str(evidence.get("summary", task.title)),
        ),
    )
    return task


def heatmap(
    session: Session,
    *,
    org_unit_id: UUID | None = None,
    skill_id: UUID | None = None,
) -> list[dict[str, Any]]:
    statement = (
        select(
            Employee.org_unit_id,
            SkillGap.skill_id,
            SkillGap.severity,
            func.count(SkillGap.id).label("count"),
        )
        .join(Employee, Employee.id == SkillGap.employee_id)
        .where(SkillGap.status.in_(("confirmed", "closed")))
        .group_by(Employee.org_unit_id, SkillGap.skill_id, SkillGap.severity)
    )
    if org_unit_id is not None:
        statement = statement.where(Employee.org_unit_id == org_unit_id)
    if skill_id is not None:
        statement = statement.where(SkillGap.skill_id == skill_id)
    rows = session.execute(statement).all()
    return [
        {
            "org_unit_id": str(org_unit_id),
            "skill_id": str(skill_id),
            "severity": severity,
            "count": count,
        }
        for org_unit_id, skill_id, severity, count in rows
    ]


def dossier(session: Session, plan: OnboardingPlan) -> dict[str, Any]:
    tasks = session.scalars(
        select(OnboardingTask)
        .where(OnboardingTask.plan_id == plan.id)
        .order_by(OnboardingTask.position)
    ).all()
    checkins = session.scalars(select(Checkin).where(Checkin.plan_id == plan.id)).all()
    gaps = session.scalars(select(SkillGap).where(SkillGap.employee_id == plan.employee_id)).all()
    return planning.dossier(
        [
            {"title": task.title, "status": task.status, "evidence": task.evidence}
            for task in tasks
        ],
        [{"status": checkin.status} for checkin in checkins],
        [
            {
                "skill_id": str(gap.skill_id),
                "current_level": gap.current_level,
                "status": gap.status,
            }
            for gap in gaps
        ],
    )

