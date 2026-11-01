"""Load the fictional journey demo. Idempotent: a second run does not duplicate rows.

The hero EMP-041 is created here only for the offline seed. In a live flow the hire
event creates the employee; this keeps the demo reproducible without a running UI.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from decimal import Decimal
from os import environ
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel import explain, trust
from kernel.db import utcnow
from kernel.identity import hash_password
from kernel.identity.models import RoleAssignment, UserAccount
from kernel.people.models import (
    Employee,
    KpiDefinition,
    OrgUnit,
    Person,
    PersonSkillEvidence,
    Position,
    Skill,
)
from kernel.trust.models import Proposal
from packs.journey.models import (
    BuddyAssignment,
    Checkin,
    Course,
    Enrollment,
    ImpactMeasure,
    OnboardingPlan,
    OnboardingTask,
    OnboardingTemplate,
    PulseResponse,
    PulseSurvey,
    SkillGap,
    SkillRequirement,
    SupportFlag,
    TemplateTask,
    TrainingRecommendation,
)

ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / "seed" / "journey"
HERO = "EMP-041"


def _read_json(name: str) -> dict[str, Any]:
    return json.loads((SEED / name).read_text(encoding="utf-8"))


def _read_csv(name: str) -> list[dict[str, str]]:
    with (SEED / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


def _maps(session: Session) -> dict[str, dict[str, Any]]:
    return {
        "employees": {row.external_id: row for row in session.scalars(select(Employee)).all()},
        "positions": {row.external_id: row for row in session.scalars(select(Position)).all()},
        "skills": {row.external_id: row for row in session.scalars(select(Skill)).all()},
        "kpis": {row.external_id: row for row in session.scalars(select(KpiDefinition)).all()},
        "orgs": {row.external_id: row for row in session.scalars(select(OrgUnit)).all()},
    }


def _users(session: Session) -> dict[UUID, UUID]:
    return {
        row.person_id: row.id
        for row in session.scalars(select(UserAccount)).all()
        if row.person_id is not None
    }


def _user_id(employee: Employee | None, users: dict[UUID, UUID]) -> UUID | None:
    if employee is None:
        return None
    return users.get(employee.person_id)


def _ensure_hero(session: Session, tenant_id: UUID, maps: dict[str, dict[str, Any]]) -> None:
    if HERO in maps["employees"]:
        return
    roster = next(
        item for item in _read_json("roster.json")["employees"] if item["employee_id"] == HERO
    )
    person = Person(tenant_id=tenant_id, external_id=HERO, lifecycle="employee")
    session.add(person)
    session.flush()
    employee = Employee(
        tenant_id=tenant_id,
        external_id=HERO,
        person_id=person.id,
        display_name=str(roster["display_name"]),
        email="yasmine.trabelsi@cds.example.test",
        org_unit_id=maps["orgs"][str(roster["org_unit_id"])].id,
        position_id=maps["positions"][str(roster["position_id"])].id,
        manager_id=maps["employees"][str(roster["manager_id"])].id,
        start_date=date.fromisoformat(str(roster["start_date"])),
    )
    session.add(employee)
    session.flush()
    maps["employees"][HERO] = employee

    email = "yasmine@cds.example.test"
    if session.scalar(select(UserAccount).where(UserAccount.email == email)) is None:
        user = UserAccount(
            tenant_id=tenant_id,
            email=email,
            password_hash=hash_password(environ["DEMO_PASSWORD"]),
            display_name=str(roster["display_name"]),
            person_id=person.id,
        )
        session.add(user)
        session.flush()
        session.add(
            RoleAssignment(
                tenant_id=tenant_id,
                user_id=user.id,
                role="employee",
            )
        )


def seed_templates(session: Session, tenant_id: UUID, maps: dict[str, dict[str, Any]]) -> dict:
    payload = _read_json("onboarding_templates.json")
    by_external: dict[str, OnboardingTemplate] = {}
    for template in payload["templates"]:
        position = maps["positions"].get(str(template["position_id"]))
        if position is None and template["position_id"] == "GENERIC":
            position = maps["positions"]["POS-FE"]
        if position is None:
            continue
        row = session.scalar(
            select(OnboardingTemplate).where(
                OnboardingTemplate.external_id == str(template["id"])
            )
        )
        if row is None:
            row = OnboardingTemplate(
                tenant_id=tenant_id,
                external_id=str(template["id"]),
                position_id=position.id,
                name=str(template["name"]),
                duration_days=int(template["duration_days"]),
                version=int(template["version"]),
                source=str(template["source"]),
                status="active",
            )
            session.add(row)
            session.flush()
            for position_number, task in enumerate(template["tasks"], start=1):
                session.add(
                    TemplateTask(
                        tenant_id=tenant_id,
                        template_id=row.id,
                        position=position_number,
                        title=str(task["title"]),
                        phase=str(task["phase"]),
                        task_kind=str(task["task_kind"]),
                        owner_role=str(task["owner_role"]),
                        due_day=int(task["due_day"]),
                        mandatory=bool(task["mandatory"]),
                        evidence_required=str(task["evidence_required"]),
                    )
                )
            session.flush()
        by_external[str(template["id"])] = row
    return by_external


def seed_requirements(
    session: Session, tenant_id: UUID, maps: dict[str, dict[str, Any]]
) -> dict[tuple[UUID, UUID], SkillRequirement]:
    result: dict[tuple[UUID, UUID], SkillRequirement] = {}
    for row in _read_csv("skill_requirements.csv"):
        position = maps["positions"].get(row["position_id"])
        skill = maps["skills"].get(row["skill_id"])
        if position is None or skill is None:
            continue
        requirement = session.scalar(
            select(SkillRequirement).where(
                SkillRequirement.position_id == position.id,
                SkillRequirement.skill_id == skill.id,
                SkillRequirement.version == 1,
            )
        )
        if requirement is None:
            requirement = SkillRequirement(
                tenant_id=tenant_id,
                position_id=position.id,
                skill_id=skill.id,
                level_required=int(row["level_required"]),
                is_mandatory=row["is_mandatory"] == "true",
                weight=Decimal(row["weight"]),
                source=row["source"],
                version=1,
            )
            session.add(requirement)
            session.flush()
        result[(position.id, skill.id)] = requirement
    return result


def seed_courses(
    session: Session, tenant_id: UUID, maps: dict[str, dict[str, Any]]
) -> dict[str, Course]:
    result: dict[str, Course] = {}
    for row in _read_csv("courses.csv"):
        skill = maps["skills"].get(row["skill_id"])
        kpi = maps["kpis"].get(row["kpi_id"])
        if skill is None or kpi is None:
            continue
        course = session.scalar(select(Course).where(Course.external_id == row["course_id"]))
        if course is None:
            course = Course(
                tenant_id=tenant_id,
                external_id=row["course_id"],
                title=row["title"],
                provider=row["provider"],
                cost_tnd=Decimal(row["cost_tnd"]),
                hours=int(row["hours"]),
                skill_id=skill.id,
                level_gained=int(row["level_gained"]),
                format=row["format"],
                url=row["url"],
                kpi_id=kpi.id,
                expected_effect=row["expected_effect"],
            )
            session.add(course)
            session.flush()
        result[row["course_id"]] = course
    return result


def seed_employee_skills(
    session: Session, tenant_id: UUID, maps: dict[str, dict[str, Any]]
) -> None:
    for row in _read_csv("employee_skills.csv"):
        employee = maps["employees"].get(row["employee_id"])
        skill = maps["skills"].get(row["skill_id"])
        if employee is None or skill is None:
            continue
        existing = session.scalar(
            select(PersonSkillEvidence).where(
                PersonSkillEvidence.person_id == employee.person_id,
                PersonSkillEvidence.skill_id == skill.id,
            )
        )
        if existing is None:
            session.add(
                PersonSkillEvidence(
                    tenant_id=tenant_id,
                    person_id=employee.person_id,
                    skill_id=skill.id,
                    level=int(row["level"]),
                    source=row["source"],
                    evidence=row["evidence"],
                )
            )
    session.flush()


def _decision_record(
    session: Session,
    tenant_id: UUID,
    gap: SkillGap,
    seed_gap: dict[str, Any],
    skill_name: str,
) -> UUID:
    factors = [
        explain.Factor(
            key=str(item["key"]),
            label=str(item["label"]),
            weight=Decimal(str(item["weight"])),
            value=Decimal(str(item["value"])),
            contribution=Decimal(str(item["contribution"])),
        )
        for item in seed_gap.get("factors", [])
    ]
    evidence = [
        explain.Evidence(
            ref=str(item.get("ref") or f"ev-{str(gap.id)[:8]}-{index}")[:16],
            factor_key=None,
            source_type=str(item.get("kind", "inferred")),
            source_id=str(item.get("ref") or seed_gap["gap_id"]),
            quote=str(item.get("summary", "seed evidence")),
        )
        for index, item in enumerate(seed_gap.get("evidence", []), start=1)
    ]
    draft = explain.DecisionDraft(
        kind="skill_gap",
        question=f"Should we confirm the {skill_name} gap for this employee?",
        outcome={
            "severity": seed_gap["severity"],
            "current_level": seed_gap["current_level"],
            "required_level": seed_gap["required_level"],
            "gap": seed_gap["gap"],
        },
        subject={"employee_id": str(gap.employee_id), "skill_id": str(gap.skill_id)},
        score=Decimal(str(seed_gap["severity_score"])) if factors else None,
        factors=factors,
        evidence=evidence,
        counterfactuals=[],
        not_considered=["name", "gender", "age", "nationality", "photo"],
        limits=[str(seed_gap["message"])],
        versions={"model": "seed", "prompt_hash": "seed"},
        view_roles=["admin", "hr", "manager", "auditor"],
    )
    record = explain.record(session, tenant_id, draft)
    return record.id


def _plan_proposal(
    session: Session,
    tenant_id: UUID,
    plan: OnboardingPlan,
    employee: Employee,
    maps: dict[str, dict[str, Any]],
    users: dict[UUID, UUID],
) -> None:
    key = f"journey.plan.activate:{plan.id}"
    if session.scalar(select(Proposal).where(Proposal.idempotency_key == key)):
        return
    draft = explain.DecisionDraft(
        kind="onboarding_plan",
        question="Should we activate this 30/60/90 plan?",
        outcome={"plan_id": str(plan.id), "phase": plan.phase},
        subject={"employee_id": str(employee.id)},
        rationale="Draft built from the role template and role profile; a human decides.",
        evidence=[
            explain.Evidence(
                ref=f"plan-{str(plan.id)[:8]}",
                factor_key=None,
                source_type="template",
                source_id=str(plan.template_id),
                quote="Role template and role-profile requirements",
            )
        ],
        not_considered=["name", "gender", "age", "nationality", "photo"],
        limits=["This is a draft; it becomes active only after approval."],
        versions={"model": "seed", "prompt_hash": "seed"},
        view_roles=["admin", "hr", "manager", "employee"],
    )
    record = explain.record(session, tenant_id, draft)
    tasks = session.scalars(
        select(OnboardingTask)
        .where(OnboardingTask.plan_id == plan.id)
        .order_by(OnboardingTask.position)
    ).all()
    buddy = session.scalar(
        select(BuddyAssignment).where(BuddyAssignment.plan_id == plan.id)
    )
    payload = {
        "plan_id": str(plan.id),
        "tasks": [
            {
                "position": task.position,
                "phase": task.phase,
                "title": task.title,
                "task_kind": task.task_kind,
                "owner_role": task.owner_role,
                "owner_employee_id": str(task.owner_employee_id)
                if task.owner_employee_id
                else None,
                "due_at": task.due_at.isoformat(),
                "mandatory": task.mandatory,
                "evidence_required": task.evidence_required,
            }
            for task in tasks
        ],
        "buddy_id": str(buddy.buddy_employee_id) if buddy else None,
    }
    trust.propose(
        session,
        tenant_id,
        "journey.plan.activate",
        payload,
        f"Activate the onboarding plan for {employee.display_name}",
        record.id,
        key,
        target={"type": "employee", "id": str(employee.id)},
        requested_by=_user_id(maps["employees"].get("EMP-006"), users),
    )


def seed(session: Session, tenant_id: UUID, world: dict) -> None:
    maps = _maps(session)
    users = _users(session)
    _ensure_hero(session, tenant_id, maps)
    maps = _maps(session)
    users = _users(session)

    templates = seed_templates(session, tenant_id, maps)
    requirements = seed_requirements(session, tenant_id, maps)
    courses = seed_courses(session, tenant_id, maps)
    seed_employee_skills(session, tenant_id, maps)

    pulse_payload = _read_json("pulse_survey.json")
    pulse_by_kind = {survey["kind"]: survey["questions"] for survey in pulse_payload["surveys"]}
    plan_payload = _read_json("plans.json")
    plan_map: dict[str, OnboardingPlan] = {}

    for seed_plan in plan_payload["plans"]:
        employee = maps["employees"].get(str(seed_plan["employee_id"]))
        template = templates.get(str(seed_plan["template_id"]))
        if employee is None or template is None:
            continue
        start = _date(str(seed_plan["start_date"]))
        existing = session.scalar(
            select(OnboardingPlan).where(
                OnboardingPlan.employee_id == employee.id,
                OnboardingPlan.start_date == start,
            )
        )
        if existing is not None:
            plan_map[str(seed_plan["employee_id"])] = existing
            continue
        plan = OnboardingPlan(
            tenant_id=tenant_id,
            employee_id=employee.id,
            template_id=template.id,
            start_date=start,
            target_ramp_date=_date(seed_plan.get("target_ramp_date")),
            status=str(seed_plan["status"]),
            phase=str(seed_plan["phase"]),
            plan_approved_by=None
            if str(seed_plan["status"]) == "draft"
            else _user_id(maps["employees"].get("EMP-006"), users),
        )
        session.add(plan)
        session.flush()
        plan_map[str(seed_plan["employee_id"])] = plan

        template_tasks = {
            row.position: row
            for row in session.scalars(
                select(TemplateTask).where(TemplateTask.template_id == template.id)
            ).all()
        }
        for seed_task in seed_plan["tasks"]:
            template_task = template_tasks.get(int(seed_task["position"]))
            owner = (
                maps["employees"].get(str(seed_task["owner_employee_id"]))
                if seed_task.get("owner_employee_id")
                else None
            )
            approver = (
                maps["employees"].get(str(seed_task["approved_by"]))
                if seed_task.get("approved_by")
                else None
            )
            session.add(
                OnboardingTask(
                    tenant_id=tenant_id,
                    plan_id=plan.id,
                    template_task_id=template_task.id if template_task else None,
                    phase=str(seed_task["phase"]),
                    position=int(seed_task["position"]),
                    title=str(seed_task["title"]),
                    task_kind=str(seed_task["task_kind"]),
                    owner_role=str(seed_task["owner_role"]),
                    owner_employee_id=owner.id if owner else None,
                    due_at=_dt(seed_task["due_at"]),
                    status=str(seed_task["status"]),
                    mandatory=bool(seed_task["mandatory"]),
                    evidence_required=str(seed_task["evidence_required"]),
                    evidence=seed_task.get("evidence"),
                    completed_at=_dt(seed_task.get("completed_at")),
                    approved_by=_user_id(approver, users),
                )
            )
        buddy_external = seed_plan.get("buddy_id")
        if buddy_external and buddy_external in maps["employees"]:
            session.add(
                BuddyAssignment(
                    tenant_id=tenant_id,
                    plan_id=plan.id,
                    buddy_employee_id=maps["employees"][str(buddy_external)].id,
                    cadence="weekly",
                    approved_by=_user_id(maps["employees"].get("EMP-002"), users),
                )
            )

        for seed_checkin in seed_plan["checkins"]:
            checkin = Checkin(
                tenant_id=tenant_id,
                plan_id=plan.id,
                kind=str(seed_checkin["kind"]),
                scheduled_at=_dt(seed_checkin["scheduled_at"]),
                completed_at=_dt(seed_checkin.get("completed_at")),
                status=str(seed_checkin["status"]),
                escalation=bool(seed_checkin.get("escalation", False)),
            )
            session.add(checkin)
            session.flush()
            questions = pulse_by_kind.get(str(seed_checkin["kind"]), [])
            survey = PulseSurvey(
                tenant_id=tenant_id,
                checkin_id=checkin.id,
                version=1,
                questions=questions,
            )
            session.add(survey)
            session.flush()
            if seed_checkin.get("answers"):
                session.add(
                    PulseResponse(
                        tenant_id=tenant_id,
                        survey_id=survey.id,
                        checkin_id=checkin.id,
                        answers=seed_checkin["answers"],
                        submitted_at=_dt(seed_checkin["completed_at"]) or utcnow(),
                    )
                )

        for seed_flag in seed_plan.get("support_flags", []):
            resolved_by = (
                maps["employees"].get(str(seed_flag["resolved_by"]))
                if seed_flag.get("resolved_by")
                else None
            )
            session.add(
                SupportFlag(
                    tenant_id=tenant_id,
                    plan_id=plan.id,
                    kind=str(seed_flag["kind"]),
                    reason_code=str(seed_flag["reason_code"]),
                    facts=seed_flag["facts"],
                    status=str(seed_flag["status"]),
                    raised_at=_dt(seed_flag["raised_at"]),
                    resolved_at=_dt(seed_flag.get("resolved_at")),
                    resolved_by=_user_id(resolved_by, users),
                )
            )

        gap_map: dict[str, SkillGap] = {}
        for seed_gap in seed_plan.get("gaps", []):
            skill = maps["skills"].get(str(seed_gap["skill_id"]))
            requirement = requirements.get((employee.position_id, skill.id)) if skill else None
            if skill is None or requirement is None:
                continue
            gap = SkillGap(
                tenant_id=tenant_id,
                employee_id=employee.id,
                skill_id=skill.id,
                requirement_id=requirement.id,
                current_level=int(seed_gap["current_level"]),
                required_level=int(seed_gap["required_level"]),
                gap=int(seed_gap["gap"]),
                severity=str(seed_gap["severity"]),
                severity_score=Decimal(str(seed_gap["severity_score"])),
                confidence=Decimal(str(seed_gap["confidence"])),
                message=str(seed_gap["message"]),
                factors=seed_gap.get("factors", []),
                evidence=seed_gap.get("evidence", []),
                status=str(seed_gap["status"]),
                decided_by=_user_id(maps["employees"].get(str(seed_gap["decided_by"])), users),
                decided_at=_dt(seed_gap.get("decided_at")),
                decision_note=seed_gap.get("decision_note"),
            )
            session.add(gap)
            session.flush()
            if gap.status in {"confirmed", "closed"}:
                gap.decision_record_id = _decision_record(
                    session, tenant_id, gap, seed_gap, skill.name
                )
            gap_map[str(seed_gap["gap_id"])] = gap

        recommendation_map: dict[str, TrainingRecommendation] = {}
        for seed_recommendation in seed_plan.get("recommendations", []):
            course = courses.get(str(seed_recommendation["course_id"]))
            gap = gap_map.get(str(seed_recommendation["gap_id"]))
            kpi = maps["kpis"].get(str(seed_recommendation["kpi_id"]))
            if course is None or gap is None or kpi is None:
                continue
            mentor = (
                maps["employees"].get(str(seed_recommendation["mentor_employee_id"]))
                if seed_recommendation.get("mentor_employee_id")
                else None
            )
            recommendation = TrainingRecommendation(
                tenant_id=tenant_id,
                gap_id=gap.id,
                employee_id=employee.id,
                kind=str(seed_recommendation["kind"]),
                course_id=course.id,
                mentor_employee_id=mentor.id if mentor else None,
                rationale=str(seed_recommendation["rationale"]),
                cost_tnd=Decimal(str(seed_recommendation["cost_tnd"])),
                hours=int(seed_recommendation["hours"]),
                kpi_id=kpi.id,
                expected_effect=str(seed_recommendation["expected_effect"]),
                status=str(seed_recommendation["status"]),
            )
            session.add(recommendation)
            session.flush()
            recommendation_map[str(seed_recommendation["recommendation_id"])] = recommendation

        for seed_enrollment in seed_plan.get("enrollments", []):
            recommendation = recommendation_map.get(str(seed_enrollment["recommendation_id"]))
            course = courses.get(str(seed_enrollment["course_id"]))
            if recommendation is None or course is None:
                continue
            verified_by = (
                maps["employees"].get(str(seed_enrollment.get("verified_by")))
                if seed_enrollment.get("verified_by")
                else None
            )
            session.add(
                Enrollment(
                    tenant_id=tenant_id,
                    recommendation_id=recommendation.id,
                    employee_id=employee.id,
                    course_id=course.id,
                    status=str(seed_enrollment["status"]),
                    started_at=_dt(seed_enrollment.get("started_at")),
                    completed_at=_dt(seed_enrollment.get("completed_at")),
                    score=(
                        Decimal(str(seed_enrollment["score"]))
                        if seed_enrollment.get("score") is not None
                        else None
                    ),
                    evidence=seed_enrollment.get("evidence", {}),
                    verified_by=_user_id(verified_by, users),
                    verified_at=_dt(seed_enrollment.get("verified_at")),
                )
            )

        for seed_impact in seed_plan.get("impact_measures", []):
            recommendation = recommendation_map.get(str(seed_impact["recommendation_id"]))
            kpi = maps["kpis"].get(str(seed_impact["kpi_id"]))
            if recommendation is None or kpi is None:
                continue
            comparison = []
            for external in seed_impact.get("comparison_employee_ids", []):
                employee_row = maps["employees"].get(str(external))
                if employee_row is not None:
                    comparison.append(str(employee_row.id))
            session.add(
                ImpactMeasure(
                    tenant_id=tenant_id,
                    recommendation_id=recommendation.id,
                    kpi_id=kpi.id,
                    baseline_value=Decimal(str(seed_impact["baseline_value"])),
                    post_value=Decimal(str(seed_impact["post_value"])),
                    delta=Decimal(str(seed_impact["delta"])),
                    comparison_employee_ids=comparison,
                    method=str(seed_impact["method"]),
                    measured_at=_dt(seed_impact["measured_at"]),
                    caveat=str(seed_impact["caveat"]),
                )
            )

    draft_plan = plan_map.get("EMP-010")
    if draft_plan is not None and draft_plan.status == "draft":
        _plan_proposal(
            session,
            tenant_id,
            draft_plan,
            maps["employees"]["EMP-010"],
            maps,
            users,
        )

    for seed_gap in plan_payload.get("background_gaps", []):
        employee = maps["employees"].get(str(seed_gap["employee_id"]))
        skill = maps["skills"].get(str(seed_gap["skill_id"]))
        requirement = (
            requirements.get((employee.position_id, skill.id))
            if employee and skill
            else None
        )
        if employee is None or skill is None or requirement is None:
            continue
        existing = session.scalar(
            select(SkillGap).where(
                SkillGap.employee_id == employee.id,
                SkillGap.skill_id == skill.id,
                SkillGap.status == str(seed_gap["status"]),
            )
        )
        if existing is not None:
            continue
        gap = SkillGap(
            tenant_id=tenant_id,
            employee_id=employee.id,
            skill_id=skill.id,
            requirement_id=requirement.id,
            current_level=int(seed_gap["current_level"]),
            required_level=int(seed_gap["required_level"]),
            gap=int(seed_gap["gap"]),
            severity=str(seed_gap["severity"]),
            severity_score=Decimal(str(seed_gap["severity_score"])),
            confidence=Decimal(str(seed_gap["confidence"])),
            message=str(seed_gap["message"]),
            factors=seed_gap.get("factors", []),
            evidence=seed_gap.get("evidence", []),
            status=str(seed_gap["status"]),
            decided_by=_user_id(maps["employees"].get(str(seed_gap["decided_by"])), users),
            decided_at=_dt(seed_gap.get("decided_at")),
            decision_note=seed_gap.get("decision_note"),
        )
        session.add(gap)
        session.flush()
        gap.decision_record_id = _decision_record(session, tenant_id, gap, seed_gap, skill.name)



