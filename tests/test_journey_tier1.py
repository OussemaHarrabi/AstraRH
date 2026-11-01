"""End-to-end backend checks for the Tier 1 gaps: portal, verify, flags, impact, Day 90."""

from datetime import date, datetime
from uuid import uuid4

from conftest import as_role, declare_action, make_user
from sqlalchemy import select

from kernel.db import tenant_session
from kernel.events.models import EventOutbox
from kernel.people.models import Employee, OrgUnit, Person, Position
from packs.journey import service
from packs.journey.handlers import activate_plan, verify_task
from packs.journey.models import Checkin, OnboardingPlan, OnboardingTask

TIER1_ACTIONS = (
    ("journey.checkin.schedule", "R1", "none"),
    ("journey.checkin.submit", "R1", "none"),
    ("journey.task.complete", "R1", "none"),
    ("journey.task.verify", "R2", "internal"),
    ("journey.support_flag.create", "R1", "none"),
    ("journey.support_flag.notify", "R2", "external"),
    ("journey.plan.complete", "R1", "none"),
)


def _make_plan(tenant):
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
            display_name="Tier One Hire",
            email="tier1@example.test",
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
        return employee.id, plan.id


def test_tier1_backend_flow(tenant):
    for action_id, risk, channel in TIER1_ACTIONS:
        declare_action(action_id, risk=risk, channel=channel)
    actor = make_user(tenant, roles=("admin",))
    make_user(tenant, roles=("hr",))
    employee_id, plan_id = _make_plan(tenant)

    with as_role("worker"), tenant_session(tenant) as session:
        activate_plan(
            session,
            tenant,
            {
                "plan_id": str(plan_id),
                "tasks": [
                    {
                        "position": 1,
                        "title": "First deliverable",
                        "phase": "week1",
                        "task_kind": "standard",
                        "owner_role": "employee",
                        "owner_employee_id": str(employee_id),
                        "due_at": datetime(2026, 11, 10, 9, 0).isoformat(),
                        "mandatory": True,
                        "evidence_required": "Deliverable link",
                    }
                ],
                "buddy_id": None,
            },
            f"tier1-activate:{plan_id}",
        )
        task = session.scalar(select(OnboardingTask).where(OnboardingTask.plan_id == plan_id))
        second = OnboardingTask(
            tenant_id=tenant,
            plan_id=plan_id,
            position=2,
            title="Old mandatory task",
            phase="week1",
            task_kind="standard",
            owner_role="employee",
            due_at=datetime(2020, 1, 1, 9, 0),
            status="pending",
            mandatory=True,
            evidence_required="Old evidence",
        )
        session.add(second)
        session.flush()
        task_id, second_id = task.id, second.id

    with as_role("api"), tenant_session(tenant) as session:
        portal = service.portal(session, actor.actor)
        assert portal["plan"].id == plan_id
        assert portal["progress"]["total"] == 2
        assert portal["cohort"]["size"] == 1
        assert portal["today"]

    with as_role("worker"), tenant_session(tenant) as session:
        task = service.complete_task(
            session,
            tenant,
            plan_id,
            task_id,
            {"summary": "Merged the first change", "url": "https://example.test/pr/1"},
            actor.actor,
        )
        assert task.status == "completed"
        proposal = service.propose_task_verification(
            session, tenant, plan_id, task_id, actor.actor, "Reviewed the PR"
        )
        assert proposal.status == "pending_approval"
        verify_task(
            session,
            tenant,
            {"task_id": str(task_id), "approved_by": str(actor.id)},
            f"tier1-verify:{task_id}",
        )
        assert task.status == "verified"
        assert task.approved_by == actor.id

        flag = service.create_support_flag(
            session,
            tenant,
            plan_id,
            "ramp_support",
            "access_blocked",
            ["Staging access is not ready"],
            actor.actor,
        )
        assert flag.status == "open"
        notified = service.notify_support_flag(
            session, tenant, plan_id, flag.id, actor.actor
        )
        assert notified.status == "pending_approval"

        swept = service.sweep_support_flags(session, tenant, plan_id, actor.actor)
        assert any(item.reason_code == "mandatory_task_overdue" for item in swept)

        service.complete_task(
            session, tenant, plan_id, second_id, {"summary": "Closed"}, actor.actor
        )
        day90 = session.scalar(
            select(Checkin).where(Checkin.plan_id == plan_id, Checkin.kind == "day90")
        )
        service.submit_checkin(
            session,
            tenant,
            plan_id,
            day90.id,
            {"role_readiness": 4, "contribution": 4},
            actor.actor,
        )
        dossier = service.complete_plan(session, tenant, plan_id, actor.actor)
        assert dossier["tasks_total"] == 2
        assert session.get(OnboardingPlan, plan_id).status == "completed"
        event = session.scalar(
            select(EventOutbox).where(
                EventOutbox.type == "journey.onboarding.completed.v1"
            )
        )
        assert event is not None
        assert event.payload["plan_id"] == str(plan_id)

    with as_role("api"), tenant_session(tenant) as session:
        plan = session.get(OnboardingPlan, plan_id)
        assert plan.status == "completed"
        assert plan.phase == "completed"


