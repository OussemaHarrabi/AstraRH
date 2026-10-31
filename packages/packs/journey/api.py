"""Journey HTTP API. Read models and the two human actions; approvals stay in trust."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel.authz import require_role
from kernel.errors import NotFound
from kernel.people.models import Employee
from kernel.web import request_context
from packs.journey import service
from packs.journey.models import (
    Checkin,
    Enrollment,
    ImpactMeasure,
    OnboardingPlan,
    OnboardingTask,
    SkillGap,
    SupportFlag,
    TrainingRecommendation,
)
from packs.journey.services import planning

router = APIRouter()

READ_ROLES = {"admin", "hr", "manager", "employee", "auditor"}
PEOPLE_ROLES = {"admin", "hr", "manager", "auditor"}
WRITE_ROLES = {"admin", "hr", "manager", "employee"}


class EvidenceBody(BaseModel):
    evidence: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None


class CheckinBody(BaseModel):
    answers: dict[str, Any] = Field(min_length=1)


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _plan_json(plan: OnboardingPlan) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "employee_id": str(plan.employee_id),
        "template_id": str(plan.template_id) if plan.template_id else None,
        "start_date": _iso(plan.start_date),
        "target_ramp_date": _iso(plan.target_ramp_date),
        "status": plan.status,
        "phase": plan.phase,
        "plan_approved_by": str(plan.plan_approved_by) if plan.plan_approved_by else None,
        "approval_id": str(plan.approval_id) if plan.approval_id else None,
    }


def _task_json(task: OnboardingTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "phase": task.phase,
        "position": task.position,
        "title": task.title,
        "task_kind": task.task_kind,
        "owner_role": task.owner_role,
        "owner_employee_id": str(task.owner_employee_id) if task.owner_employee_id else None,
        "due_at": _iso(task.due_at),
        "status": task.status,
        "mandatory": task.mandatory,
        "evidence_required": task.evidence_required,
        "evidence": task.evidence,
        "completed_at": _iso(task.completed_at),
        "approved_by": str(task.approved_by) if task.approved_by else None,
    }


def _checkin_json(checkin: Checkin) -> dict[str, Any]:
    return {
        "id": str(checkin.id),
        "kind": checkin.kind,
        "scheduled_at": _iso(checkin.scheduled_at),
        "completed_at": _iso(checkin.completed_at),
        "status": checkin.status,
        "escalation": checkin.escalation,
    }


def _flag_json(flag: SupportFlag) -> dict[str, Any]:
    return {
        "id": str(flag.id),
        "kind": flag.kind,
        "reason_code": flag.reason_code,
        "facts": flag.facts,
        "status": flag.status,
        "raised_at": _iso(flag.raised_at),
        "resolved_at": _iso(flag.resolved_at),
        "resolved_by": str(flag.resolved_by) if flag.resolved_by else None,
    }


def _gap_json(gap: SkillGap) -> dict[str, Any]:
    return {
        "id": str(gap.id),
        "employee_id": str(gap.employee_id),
        "skill_id": str(gap.skill_id),
        "requirement_id": str(gap.requirement_id),
        "current_level": gap.current_level,
        "required_level": gap.required_level,
        "gap": gap.gap,
        "severity": gap.severity,
        "severity_score": str(gap.severity_score),
        "confidence": str(gap.confidence),
        "message": gap.message,
        "factors": gap.factors,
        "evidence": gap.evidence,
        "status": gap.status,
        "decided_by": str(gap.decided_by) if gap.decided_by else None,
        "decided_at": _iso(gap.decided_at),
        "decision_note": gap.decision_note,
        "decision_record_id": str(gap.decision_record_id) if gap.decision_record_id else None,
    }


def _recommendation_json(item: TrainingRecommendation) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "gap_id": str(item.gap_id),
        "employee_id": str(item.employee_id),
        "kind": item.kind,
        "course_id": str(item.course_id) if item.course_id else None,
        "mentor_employee_id": str(item.mentor_employee_id) if item.mentor_employee_id else None,
        "rationale": item.rationale,
        "cost_tnd": str(item.cost_tnd),
        "hours": item.hours,
        "kpi_id": str(item.kpi_id),
        "expected_effect": item.expected_effect,
        "status": item.status,
        "approval_id": str(item.approval_id) if item.approval_id else None,
    }


def _enrollment_json(item: Enrollment) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "recommendation_id": str(item.recommendation_id),
        "employee_id": str(item.employee_id),
        "course_id": str(item.course_id),
        "status": item.status,
        "started_at": _iso(item.started_at),
        "completed_at": _iso(item.completed_at),
        "score": str(item.score) if item.score is not None else None,
        "evidence": item.evidence,
        "verified_by": str(item.verified_by) if item.verified_by else None,
        "verified_at": _iso(item.verified_at),
    }


def _impact_json(item: ImpactMeasure) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "recommendation_id": str(item.recommendation_id),
        "kpi_id": str(item.kpi_id),
        "baseline_value": str(item.baseline_value),
        "post_value": str(item.post_value),
        "delta": str(item.delta),
        "comparison_employee_ids": item.comparison_employee_ids,
        "method": item.method,
        "measured_at": _iso(item.measured_at),
        "caveat": item.caveat,
    }


def _visible_employee_ids(session: Session, actor) -> set[UUID] | None:
    if actor.roles & {"admin", "hr", "auditor"}:
        return None
    employee = service.employee_for_actor(session, actor)
    if employee is None:
        return set()
    ids = {employee.id}
    if "manager" in actor.roles:
        ids.update(
            session.scalars(
                select(Employee.id).where(Employee.manager_id == employee.id)
            ).all()
        )
    return ids


@router.get("/plans", summary="Plans visible to the signed-in user")
def list_plans(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        return [_plan_json(plan) for plan in service.plans_for_actor(ctx.session, ctx.actor)]


@router.get("/plans/me", summary="The signed-in employee's own plan")
def my_plan(request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        plans = service.plans_for_actor(ctx.session, ctx.actor)
        if not plans:
            raise NotFound("No plan for this user")
        return _plan_json(plans[0])


@router.get("/plans/{plan_id}", summary="A plan with tasks, check-ins and flags")
def get_plan(plan_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        plan = service.plan_for_actor(ctx.session, ctx.actor, plan_id)
        tasks = ctx.session.scalars(
            select(OnboardingTask)
            .where(OnboardingTask.plan_id == plan.id)
            .order_by(OnboardingTask.position)
        ).all()
        checkins = ctx.session.scalars(
            select(Checkin).where(Checkin.plan_id == plan.id).order_by(Checkin.scheduled_at)
        ).all()
        flags = ctx.session.scalars(
            select(SupportFlag)
            .where(SupportFlag.plan_id == plan.id)
            .order_by(SupportFlag.raised_at)
        ).all()
        gaps = ctx.session.scalars(
            select(SkillGap).where(SkillGap.employee_id == plan.employee_id)
        ).all()
        recommendations = ctx.session.scalars(
            select(TrainingRecommendation).where(
                TrainingRecommendation.employee_id == plan.employee_id
            )
        ).all()
        enrollments = ctx.session.scalars(
            select(Enrollment).where(Enrollment.employee_id == plan.employee_id)
        ).all()
        impact = ctx.session.scalars(
            select(ImpactMeasure)
            .join(
                TrainingRecommendation,
                ImpactMeasure.recommendation_id == TrainingRecommendation.id,
            )
            .where(TrainingRecommendation.employee_id == plan.employee_id)
        ).all()
        today = datetime.now().astimezone()
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
                }
                for checkin in checkins
            ],
            today,
        )
        return {
            **_plan_json(plan),
            "tasks": [_task_json(task) for task in tasks],
            "checkins": [_checkin_json(checkin) for checkin in checkins],
            "support_flags": [_flag_json(flag) for flag in flags],
            "gaps": [_gap_json(gap) for gap in gaps],
            "recommendations": [_recommendation_json(item) for item in recommendations],
            "enrollments": [_enrollment_json(item) for item in enrollments],
            "impact_measures": [_impact_json(item) for item in impact],
            "attention": {
                "level": attention.level,
                "facts": attention.facts,
                "codes": attention.codes,
            },
        }


@router.post("/plans/{plan_id}/tasks/{task_id}/complete", summary="Record task evidence")
def complete_task(
    plan_id: UUID, task_id: UUID, body: EvidenceBody, request: Request
) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        evidence = dict(body.evidence)
        if body.summary:
            evidence.setdefault("summary", body.summary)
        task = service.complete_task(
            ctx.session, ctx.actor.tenant_id, plan_id, task_id, evidence, ctx.actor
        )
        return _task_json(task)


@router.post("/plans/{plan_id}/checkins/{checkin_id}/submit", summary="Submit a structured pulse")
def submit_checkin(
    plan_id: UUID, checkin_id: UUID, body: CheckinBody, request: Request
) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        checkin = service.submit_checkin(
            ctx.session, ctx.actor.tenant_id, plan_id, checkin_id, body.answers, ctx.actor
        )
        return _checkin_json(checkin)


@router.get("/plans/{plan_id}/dossier", summary="Day-90 review pack")
def get_dossier(plan_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        plan = service.plan_for_actor(ctx.session, ctx.actor, plan_id)
        return service.dossier(ctx.session, plan)


@router.get("/gaps", summary="Skill gaps, filtered by role")
def list_gaps(
    request: Request,
    employee_id: UUID | None = None,
    skill_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        statement = select(SkillGap).order_by(SkillGap.created_at.desc())
        visible = _visible_employee_ids(ctx.session, ctx.actor)
        if visible is not None:
            statement = statement.where(SkillGap.employee_id.in_(visible))
        if employee_id is not None:
            statement = statement.where(SkillGap.employee_id == employee_id)
        if skill_id is not None:
            statement = statement.where(SkillGap.skill_id == skill_id)
        return [_gap_json(gap) for gap in ctx.session.scalars(statement).all()]


@router.get("/recommendations", summary="Training recommendations, filtered by role")
def list_recommendations(
    request: Request,
    employee_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        statement = select(TrainingRecommendation).order_by(
            TrainingRecommendation.created_at.desc()
        )
        visible = _visible_employee_ids(ctx.session, ctx.actor)
        if visible is not None:
            statement = statement.where(TrainingRecommendation.employee_id.in_(visible))
        if employee_id is not None:
            statement = statement.where(TrainingRecommendation.employee_id == employee_id)
        return [_recommendation_json(item) for item in ctx.session.scalars(statement).all()]


@router.get("/impact", summary="Observed training impact")
def list_impact(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, PEOPLE_ROLES)
        statement = (
            select(ImpactMeasure)
            .join(
                TrainingRecommendation,
                ImpactMeasure.recommendation_id == TrainingRecommendation.id,
            )
            .order_by(ImpactMeasure.measured_at.desc())
        )
        visible = _visible_employee_ids(ctx.session, ctx.actor)
        if visible is not None:
            statement = statement.where(TrainingRecommendation.employee_id.in_(visible))
        rows = ctx.session.scalars(statement).all()
        return [_impact_json(item) for item in rows]


@router.get("/heatmap", summary="Team x skill heatmap, k >= 5 only")
def get_heatmap(
    request: Request,
    org_unit_id: UUID | None = Query(default=None),
    skill_id: UUID | None = Query(default=None),
) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, PEOPLE_ROLES)
        rows = service.heatmap(ctx.session, org_unit_id=org_unit_id, skill_id=skill_id)
        cells: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["org_unit_id"], row["skill_id"])
            cell = cells.setdefault(
                key,
                {"org_unit_id": row["org_unit_id"], "skill_id": row["skill_id"],
                 "count": 0, "severity": {}},
            )
            cell["count"] += row["count"]
            current = cell["severity"].get(row["severity"], 0)
            cell["severity"][row["severity"]] = current + row["count"]
        result: list[dict[str, Any]] = []
        for cell in cells.values():
            if cell["count"] < 5:
                result.append(
                    {
                        "org_unit_id": cell["org_unit_id"],
                        "skill_id": cell["skill_id"],
                        "suppressed": True,
                        "reason": "insufficient_group",
                    }
                )
                continue
            result.append({**cell, "suppressed": False})
        return sorted(result, key=lambda item: (item["org_unit_id"], item["skill_id"]))


