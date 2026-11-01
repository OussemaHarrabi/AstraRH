"""Journey operations shared by the HTTP API, the seed loader and the handlers."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kernel import explain, trust
from kernel.db import utcnow
from kernel.errors import Conflict, NotFound, ValidationFailed
from kernel.events import publish
from kernel.identity.models import RoleAssignment, UserAccount
from kernel.people.models import Employee
from packs.journey.events import EvidenceRecorded, OnboardingCompleted, PulseSubmitted
from packs.journey.models import (
    BuddyAssignment,
    Checkin,
    ImpactMeasure,
    OnboardingPlan,
    OnboardingTask,
    PulseResponse,
    PulseSurvey,
    SkillGap,
    SupportFlag,
    TrainingRecommendation,
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
    if task.status in {"completed", "verified"}:
        return task
    if task.evidence_required and not evidence:
        raise ValidationFailed("This milestone needs evidence before it can be completed")
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


def propose_task_verification(
    session: Session,
    tenant_id: UUID,
    plan_id: UUID,
    task_id: UUID,
    actor,
    note: str | None = None,
) -> Any:
    plan = plan_for_actor(session, actor, plan_id)
    task = session.get(OnboardingTask, task_id)
    if task is None or task.plan_id != plan.id:
        raise NotFound("Task not found")
    if task.status != "completed":
        raise Conflict("Only a completed milestone can be verified")
    if not task.evidence:
        raise ValidationFailed("A verified milestone needs evidence")
    evidence = task.evidence or {}
    decision = explain.record(
        session,
        tenant_id,
        explain.DecisionDraft(
            kind="task_verification",
            question="Should this onboarding milestone be verified?",
            outcome={"task_id": str(task.id), "status": "verified"},
            subject={"employee_id": str(plan.employee_id), "task_id": str(task.id)},
            rationale=note or f"Review of {task.evidence_required}",
            evidence=[
                explain.Evidence(
                    ref=f"task-{str(task.id)[:8]}",
                    source_type="onboarding_task",
                    source_id=str(task.id),
                    quote=str(evidence.get("summary", task.title)),
                )
            ],
            view_roles=["admin", "hr", "manager", "employee"],
        ),
    )
    return trust.propose(
        session,
        tenant_id,
        "journey.task.verify",
        {
            "task_id": str(task.id),
            "approved_by": str(actor.user_id),
            "decision_note": note or "Milestone evidence reviewed",
        },
        f"Verify milestone: {task.title}",
        decision.id,
        f"task-verify:{task.id}:{task.status}",
        target={"type": "employee", "id": str(plan.employee_id)},
        requested_by=actor.user_id,
    )


def record_impact(
    session: Session,
    tenant_id: UUID,
    recommendation_id: UUID,
    *,
    baseline_value: Decimal,
    post_value: Decimal,
    comparison_employee_ids: list[UUID],
    method: str,
    caveat: str,
    actor,
) -> ImpactMeasure:
    recommendation = session.get(TrainingRecommendation, recommendation_id)
    if recommendation is None:
        raise NotFound("Training recommendation not found")
    existing = session.scalar(
        select(ImpactMeasure).where(
            ImpactMeasure.recommendation_id == recommendation.id,
            ImpactMeasure.kpi_id == recommendation.kpi_id,
        )
    )
    if existing is not None:
        raise Conflict("An impact measure already exists for this recommendation and KPI")
    row = ImpactMeasure(
        tenant_id=tenant_id,
        recommendation_id=recommendation.id,
        kpi_id=recommendation.kpi_id,
        baseline_value=baseline_value,
        post_value=post_value,
        delta=post_value - baseline_value,
        comparison_employee_ids=[str(item) for item in comparison_employee_ids],
        method=method,
        measured_at=utcnow(),
        caveat=caveat,
    )
    session.add(row)
    session.flush()
    trust.log_action(
        session,
        tenant_id,
        "journey.impact.record",
        "human",
        str(actor.user_id),
        impact_id=str(row.id),
        recommendation_id=str(recommendation.id),
    )
    return row


def create_support_flag(
    session: Session,
    tenant_id: UUID,
    plan_id: UUID,
    kind: str,
    reason_code: str,
    facts: list[str],
    actor,
) -> SupportFlag:
    plan = plan_for_actor(session, actor, plan_id)
    if not reason_code.strip() or not facts:
        raise ValidationFailed("A support flag needs a reason and at least one fact")
    existing = session.scalar(
        select(SupportFlag).where(
            SupportFlag.plan_id == plan.id,
            SupportFlag.reason_code == reason_code,
            SupportFlag.status == "open",
        )
    )
    if existing is not None:
        return existing
    flag = SupportFlag(
        tenant_id=tenant_id,
        plan_id=plan.id,
        kind=kind or "ramp_support",
        reason_code=reason_code,
        facts=list(facts),
        status="open",
        raised_at=utcnow(),
    )
    session.add(flag)
    session.flush()
    trust.log_action(
        session,
        tenant_id,
        "journey.support_flag.create",
        "human",
        str(actor.user_id),
        flag_id=str(flag.id),
        plan_id=str(plan.id),
    )
    return flag


def sweep_support_flags(
    session: Session,
    tenant_id: UUID,
    plan_id: UUID,
    actor,
) -> list[SupportFlag]:
    plan = plan_for_actor(session, actor, plan_id)
    tasks = session.scalars(select(OnboardingTask).where(OnboardingTask.plan_id == plan.id)).all()
    checkins = session.scalars(select(Checkin).where(Checkin.plan_id == plan.id)).all()
    responses = (
        session.scalars(
            select(PulseResponse).where(PulseResponse.checkin_id.in_([row.id for row in checkins]))
        ).all()
        if checkins
        else []
    )
    answers = {row.checkin_id: row.answers for row in responses}
    attention = planning.attention(
        [
            {
                "title": task.title,
                "status": task.status,
                "due_at": task.due_at,
                "mandatory": task.mandatory,
            }
            for task in tasks
        ],
        [
            {
                "kind": checkin.kind,
                "status": checkin.status,
                "scheduled_at": checkin.scheduled_at,
                "answers": answers.get(checkin.id, {}),
            }
            for checkin in checkins
        ],
        datetime.now().astimezone(),
    )
    created: list[SupportFlag] = []
    for code, fact in zip(attention.codes, attention.facts, strict=False):
        existing = session.scalar(
            select(SupportFlag).where(
                SupportFlag.plan_id == plan.id,
                SupportFlag.reason_code == code,
                SupportFlag.status == "open",
            )
        )
        if existing is not None:
            continue
        flag = SupportFlag(
            tenant_id=tenant_id,
            plan_id=plan.id,
            kind="ramp_support",
            reason_code=code,
            facts=[fact],
            status="open",
            raised_at=utcnow(),
        )
        session.add(flag)
        session.flush()
        created.append(flag)
    if created:
        trust.log_action(
            session,
            tenant_id,
            "journey.support_flag.create",
            "system",
            "worker",
            plan_id=str(plan.id),
            flags=len(created),
        )
    return created


def notify_support_flag(
    session: Session,
    tenant_id: UUID,
    plan_id: UUID,
    flag_id: UUID,
    actor,
) -> Any:
    plan = plan_for_actor(session, actor, plan_id)
    flag = session.get(SupportFlag, flag_id)
    if flag is None or flag.plan_id != plan.id:
        raise NotFound("Support flag not found")
    if flag.status != "open":
        raise Conflict("Only an open support flag can be notified")
    hr_user = session.scalar(
        select(UserAccount)
        .join(RoleAssignment, RoleAssignment.user_id == UserAccount.id)
        .where(RoleAssignment.role == "hr")
        .limit(1)
    )
    employee = session.get(Employee, plan.employee_id)
    if hr_user is None or employee is None:
        raise ValidationFailed("No HR recipient or employee record for this flag")
    body = (
        f"Support flag for {employee.display_name}: {flag.reason_code}.\n"
        f"Facts: {'; '.join(flag.facts)}\n"
        f"Plan: {plan.id}"
    )
    decision = explain.record(
        session,
        tenant_id,
        explain.DecisionDraft(
            kind="support_flag_notify",
            question="Should HR be notified about this support flag?",
            outcome={"flag_id": str(flag.id), "status": "notify"},
            subject={"employee_id": str(plan.employee_id), "flag_id": str(flag.id)},
            rationale="A factual support flag needs a human response.",
            evidence=[
                explain.Evidence(
                    ref=f"flag-{str(flag.id)[:8]}",
                    source_type="support_flag",
                    source_id=str(flag.id),
                    quote="; ".join(flag.facts),
                )
            ],
            view_roles=["admin", "hr", "manager"],
        ),
    )
    return trust.propose(
        session,
        tenant_id,
        "journey.support_flag.notify",
        {
            "to": hr_user.email,
            "subject": f"Support flag: {employee.display_name}",
            "body": body,
            "flag_id": str(flag.id),
        },
        f"Notify HR about {flag.reason_code}",
        decision.id,
        f"support-flag-notify:{flag.id}:{flag.reason_code}",
        target={"type": "employee", "id": str(plan.employee_id)},
        requested_by=actor.user_id,
    )


def portal(session: Session, actor) -> dict[str, Any]:
    plans = plans_for_actor(session, actor)
    if not plans:
        raise NotFound("No plan for this user")
    plan = plans[0]
    tasks = session.scalars(
        select(OnboardingTask)
        .where(OnboardingTask.plan_id == plan.id)
        .order_by(OnboardingTask.position)
    ).all()
    checkins = session.scalars(
        select(Checkin).where(Checkin.plan_id == plan.id).order_by(Checkin.scheduled_at)
    ).all()
    buddy = session.scalar(select(BuddyAssignment).where(BuddyAssignment.plan_id == plan.id))
    buddy_employee = (
        session.get(Employee, buddy.buddy_employee_id)
        if buddy is not None and buddy.buddy_employee_id is not None
        else None
    )
    cohort_size = session.scalar(
        select(func.count(Employee.id)).where(Employee.start_date == plan.start_date)
    )
    task_rows = [
        {
            "id": str(task.id),
            "title": task.title,
            "phase": task.phase,
            "owner_role": task.owner_role,
            "status": task.status,
            "due_at": task.due_at,
            "mandatory": task.mandatory,
            "evidence_required": task.evidence_required,
        }
        for task in tasks
    ]
    today = planning.next_three(task_rows, datetime.now().astimezone())
    for row in today:
        row["due_at"] = row["due_at"].isoformat()
    completed = sum(1 for task in tasks if task.status in {"completed", "verified"})
    next_checkin = next((row for row in checkins if row.status == "pending"), None)
    return {
        "plan": plan,
        "today": today,
        "progress": {
            "completed": completed,
            "total": len(tasks),
            "percent": round(completed * 100 / len(tasks)) if tasks else 0,
            "mandatory_open": sum(
                1
                for task in tasks
                if task.mandatory and task.status not in {"completed", "verified"}
            ),
        },
        "buddy": (
            {
                "employee_id": str(buddy.buddy_employee_id),
                "display_name": buddy_employee.display_name if buddy_employee else None,
                "cadence": buddy.cadence,
            }
            if buddy is not None
            else None
        ),
        "cohort": {"start_date": plan.start_date.isoformat(), "size": int(cohort_size or 0)},
        "next_checkin": next_checkin,
        "ask": {"enabled": False, "reason": "preview"},
    }


def complete_plan(session: Session, tenant_id: UUID, plan_id: UUID, actor) -> dict[str, Any]:
    plan = plan_for_actor(session, actor, plan_id)
    if plan.status == "completed":
        raise Conflict("This onboarding plan is already completed")
    tasks = session.scalars(select(OnboardingTask).where(OnboardingTask.plan_id == plan.id)).all()
    checkins = session.scalars(select(Checkin).where(Checkin.plan_id == plan.id)).all()
    day90 = next((row for row in checkins if row.kind == "day90"), None)
    if day90 is None or day90.status != "completed":
        raise Conflict("The Day-90 check-in must be completed first")
    open_mandatory = [
        task
        for task in tasks
        if task.mandatory and task.status not in {"completed", "verified"}
    ]
    if open_mandatory:
        raise Conflict("Mandatory milestones are still open")
    gap_rows = session.scalars(
        select(SkillGap).where(SkillGap.employee_id == plan.employee_id)
    ).all()
    verified_skills = [
        {"skill_id": str(gap.skill_id), "level": gap.current_level}
        for gap in gap_rows
        if gap.status in {"verified", "closed"}
    ]
    plan.status = "completed"
    plan.phase = "completed"
    publish(
        session,
        tenant_id,
        OnboardingCompleted(
            plan_id=plan.id,
            employee_id=plan.employee_id,
            completed_at=utcnow(),
            milestones_total=len(tasks),
            milestones_with_evidence=sum(
                1
                for task in tasks
                if task.status in {"completed", "verified"} and bool(task.evidence)
            ),
            verified_skills=verified_skills,
        ),
    )
    trust.log_action(
        session,
        tenant_id,
        "journey.plan.complete",
        "human",
        str(actor.user_id),
        plan_id=str(plan.id),
        milestones_total=len(tasks),
    )
    return dossier(session, plan)


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



