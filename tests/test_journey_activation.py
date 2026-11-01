"""DB-level proof that an approved plan applies tasks and schedules its check-ins."""

from datetime import date
from uuid import uuid4

from conftest import as_role, declare_action
from sqlalchemy import select

from kernel.db import tenant_session
from kernel.people.models import Employee, OrgUnit, Person, Position
from kernel.trust import audit
from packs.journey.handlers import activate_plan
from packs.journey.models import Checkin, OnboardingPlan, PulseSurvey


def test_activation_schedules_four_pulse_checkins(tenant):
    declare_action("journey.checkin.schedule", risk="R1", channel="none")
    with as_role("owner"), tenant_session(tenant) as session:
        person = Person(
            tenant_id=tenant,
            external_id=f"P-{uuid4().hex[:8]}",
            lifecycle="employee",
        )
        org_unit = OrgUnit(
            tenant_id=tenant,
            external_id=f"ORG-{uuid4().hex[:8]}",
            name="Engineering",
        )
        position = Position(
            tenant_id=tenant,
            external_id=f"POS-{uuid4().hex[:8]}",
            title="Backend Engineer",
        )
        session.add_all([person, org_unit, position])
        session.flush()
        employee = Employee(
            tenant_id=tenant,
            external_id=f"EMP-{uuid4().hex[:8]}",
            person_id=person.id,
            display_name="Test Hire",
            email="hire@example.test",
            org_unit_id=org_unit.id,
            position_id=position.id,
            start_date=date(2026, 11, 9),
            status="active",
        )
        session.add(employee)
        session.flush()
        plan = OnboardingPlan(
            tenant_id=tenant,
            employee_id=employee.id,
            start_date=date(2026, 11, 9),
            status="draft",
            phase="preboarding",
        )
        session.add(plan)
        session.flush()
        plan_id = plan.id

    with as_role("worker"), tenant_session(tenant) as session:
        activate_plan(
            session,
            tenant,
            {"plan_id": str(plan_id), "tasks": [], "buddy_id": None},
            f"test:activation:{plan_id}",
        )

    with as_role("api"), tenant_session(tenant) as session:
        plan = session.get(OnboardingPlan, plan_id)
        checkins = session.scalars(
            select(Checkin)
            .where(Checkin.plan_id == plan_id)
            .order_by(Checkin.scheduled_at)
        ).all()
        surveys = session.scalars(
            select(PulseSurvey).where(PulseSurvey.checkin_id.in_([row.id for row in checkins]))
        ).all()

        assert plan.status == "in_progress"
        assert [row.kind for row in checkins] == ["day7", "day30", "day60", "day90"]
        assert all(row.status == "pending" for row in checkins)
        assert len(surveys) == 4
        assert all(survey.questions for survey in surveys)
        assert any(
            question["id"] == "access_ready"
            for survey in surveys
            for question in survey.questions
        )
        assert audit.verify_chain(session).ok
