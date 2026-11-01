"""HR turns a hired person into an employee; the event is what starts onboarding."""

import os
from datetime import date
from uuid import uuid4

import pytest
from conftest import TEST_PASSWORD, as_role, make_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from kernel import events, registry, web
from kernel.ai.graphs import setup_checkpoints
from kernel.db import global_session, tenant_session
from kernel.events.models import EventOutbox
from kernel.identity.models import Tenant
from kernel.people.models import OrgUnit, Person, Position
from kernel.trust.models import Proposal
from packs.journey.models import OnboardingTemplate, TemplateTask

app = FastAPI()
web.install(app)


@pytest.fixture(autouse=True)
def api_role():
    with as_role("api"):
        yield


@pytest.fixture
def slug(tenant):
    with as_role("owner"), global_session() as session:
        return session.get(Tenant, tenant).slug


def signed_in(slug, user) -> TestClient:
    http = TestClient(app, base_url="http://testserver", raise_server_exceptions=True)
    response = http.post(
        "/auth/login", json={"tenant": slug, "email": user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    http.headers["x-csrf-token"] = http.cookies[web.CSRF_COOKIE]
    return http


def test_hr_creates_an_employee_and_onboarding_is_proposed(tenant, slug, monkeypatch):
    suffix = uuid4().hex[:8]
    with as_role("owner"), tenant_session(tenant) as session:
        person = Person(tenant_id=tenant, external_id=f"P-{suffix}", lifecycle="candidate")
        org = OrgUnit(tenant_id=tenant, external_id=f"O-{suffix}", name="Engineering")
        position = Position(tenant_id=tenant, external_id=f"R-{suffix}", title="Engineer")
        session.add_all([person, org, position])
        session.flush()
        person_id, org_id, position_id = person.id, org.id, position.id
        template = OnboardingTemplate(
            tenant_id=tenant,
            external_id=f"TPL-{suffix}",
            position_id=position_id,
            name="Engineer onboarding",
            duration_days=90,
            version=1,
            source="test",
            status="active",
        )
        session.add(template)
        session.flush()
        session.add(
            TemplateTask(
                tenant_id=tenant,
                template_id=template.id,
                position=1,
                title="Meet the team",
                phase="week1",
                task_kind="standard",
                owner_role="employee",
                due_day=1,
                mandatory=True,
                evidence_required="Meeting notes",
            )
        )

    hr = signed_in(slug, make_user(tenant, ("hr",)))
    response = hr.post(
        "/people/employees",
        json={
            "person_id": str(person_id),
            "display_name": "Yasmine Trabelsi",
            "email": f"yasmine-{suffix}@example.test",
            "org_unit_id": str(org_id),
            "position_id": str(position_id),
            "start_date": "2026-12-01",
        },
    )
    assert response.status_code == 201, response.text
    employee = response.json()
    assert employee["person_id"] == str(person_id)

    with as_role("owner"), tenant_session(tenant) as session:
        event = session.scalar(
            select(EventOutbox).where(EventOutbox.type == "core.employee.created.v1")
        )
    assert event is not None
    assert event.payload["employee_id"] == employee["id"]
    assert event.payload["start_date"] == "2026-12-01"
    assert date.fromisoformat(event.payload["start_date"]) == date(2026, 12, 1)

    monkeypatch.setenv("AGENTS_INLINE", "1")
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_WORKER_URL"])
    setup_checkpoints()
    registry.wire_agents()
    with as_role("worker"):
        events.relay_once(tenant)
    with as_role("owner"), tenant_session(tenant) as session:
        proposals = session.scalars(
            select(Proposal).where(Proposal.action_type == "journey.plan.activate")
        ).all()
    assert proposals
    assert proposals[0].target["org_unit"] == f"O-{suffix}"
