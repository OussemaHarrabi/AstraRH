"""Hiring a candidate: the R3 action, the event, and the hand-off to finance.

Proposals are created through the worker because the API role cannot insert them yet (kernel
request K9, docs/FINANCE_PAYMENT_DESIGN.md)."""

from uuid import UUID, uuid4

import pytest
from conftest import TEST_PASSWORD, as_role, make_decision, make_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from finance_helpers import make_employee
from sqlalchemy import select

from kernel import events, registry, trust, web
from kernel.db import global_session, tenant_session
from kernel.errors import PermissionDenied
from kernel.events.models import EventOutbox
from kernel.identity.models import Tenant
from kernel.trust.models import Proposal
from packs.finance import api as finance_api
from packs.finance import consumers  # noqa: F401 - registers the finance consumer
from packs.talent import api as talent_api
from packs.talent.models import Application, Candidate, Job, StageEvent

ACTION = "talent.application.hire"

app = FastAPI()
web.install(app)
app.include_router(talent_api.router, prefix="/packs/talent")
app.include_router(finance_api.router, prefix="/packs/finance")


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


def make_application(tenant_id: UUID, stage: str) -> dict[str, UUID]:
    from kernel.people.models import Person

    suffix = uuid4().hex[:8]
    with as_role("owner"), tenant_session(tenant_id) as session:
        person = Person(tenant_id=tenant_id, external_id=f"CAND-{suffix}", lifecycle="candidate")
        job = Job(
            tenant_id=tenant_id,
            external_id=f"JOB-{suffix}",
            title="Backend Engineer",
            description="Build and run the payroll backend services.",
        )
        session.add_all([person, job])
        session.flush()
        candidate = Candidate(tenant_id=tenant_id, person_id=person.id)
        session.add(candidate)
        session.flush()
        application = Application(
            tenant_id=tenant_id, job_id=job.id, candidate_id=candidate.id, stage=stage
        )
        session.add(application)
        session.flush()
        return {
            "application": application.id,
            "job": job.id,
            "candidate": candidate.id,
            "person": person.id,
        }


def propose_hire(tenant, requester, ids, reason="Strong interview", attempt=1) -> Proposal:
    decision = make_decision(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        return trust.propose(
            session,
            tenant,
            ACTION,
            {"application_id": str(ids["application"]), "reason": reason},
            "Hire this candidate",
            decision,
            f"hire:{ids['application']}:{attempt}",
            target={"job_id": str(ids["job"])},
            requested_by=requester.id,
        )


def approve(tenant, approver, proposal_id: UUID) -> None:
    with as_role("api"), tenant_session(tenant) as session:
        trust.approve(session, approver.actor, proposal_id)


def run_actions(tenant) -> int:
    with as_role("worker"):
        return registry.run_internal_actions(tenant)


def stage_of(tenant, application_id: UUID) -> str:
    with as_role("worker"), tenant_session(tenant) as session:
        return session.get(Application, application_id).stage


def proposal_status(tenant, proposal_id: UUID) -> str:
    with as_role("worker"), tenant_session(tenant) as session:
        return session.get(Proposal, proposal_id).status


def hire(tenant, ids) -> Proposal:
    requester = make_user(tenant, ("recruiter",))
    approver = make_user(tenant, ("hr",), step_up=True)
    proposal = propose_hire(tenant, requester, ids)
    approve(tenant, approver, proposal.id)
    run_actions(tenant)
    return proposal


def outbox(tenant, kind: str) -> list[EventOutbox]:
    with as_role("worker"), tenant_session(tenant) as session:
        return session.scalars(select(EventOutbox).where(EventOutbox.type == kind)).all()


@pytest.mark.parametrize("stage", ["shortlisted", "interview"])
def test_a_shortlisted_or_interviewed_candidate_can_be_hired(tenant, stage):
    ids = make_application(tenant, stage)
    proposal = hire(tenant, ids)
    assert proposal_status(tenant, proposal.id) == "executed"
    assert stage_of(tenant, ids["application"]) == "hired"
    with as_role("worker"), tenant_session(tenant) as session:
        history = session.scalars(select(StageEvent)).all()
    assert [(h.from_stage, h.to_stage, h.reason) for h in history] == [
        (stage, "hired", "Strong interview")
    ]


def test_hiring_announces_the_candidate_and_person_ids_only(tenant):
    ids = make_application(tenant, "interview")
    hire(tenant, ids)
    [event] = outbox(tenant, "talent.candidate.hired.v1")
    assert event.payload == {
        "application_id": str(ids["application"]),
        "job_id": str(ids["job"]),
        "candidate_id": str(ids["candidate"]),
        "person_id": str(ids["person"]),
    }
    assert len(outbox(tenant, "talent.application.stage_changed.v1")) == 1


@pytest.mark.parametrize("stage", ["applied", "rejected", "hired_elsewhere"])
def test_a_candidate_at_any_other_stage_cannot_be_hired(tenant, stage):
    ids = make_application(tenant, stage)
    proposal = hire(tenant, ids)
    assert proposal_status(tenant, proposal.id) == "failed"
    assert stage_of(tenant, ids["application"]) == stage
    assert outbox(tenant, "talent.candidate.hired.v1") == []


def test_hiring_needs_a_second_person_and_a_fresh_password(tenant):
    ids = make_application(tenant, "interview")
    requester = make_user(tenant, ("hr",), step_up=True)
    proposal = propose_hire(tenant, requester, ids)
    assert (proposal.risk, proposal.status) == ("R3", "pending_approval")
    with as_role("api"), tenant_session(tenant) as session, pytest.raises(PermissionDenied):
        trust.approve(session, requester.actor, proposal.id)
    with (
        as_role("api"),
        tenant_session(tenant) as session,
        pytest.raises(Exception, match="password"),
    ):
        trust.approve(session, make_user(tenant, ("hr",), step_up=False).actor, proposal.id)
    assert stage_of(tenant, ids["application"]) == "interview"


def test_a_recruiter_cannot_approve_a_hire(tenant):
    ids = make_application(tenant, "interview")
    proposal = propose_hire(tenant, make_user(tenant, ("recruiter",)), ids)
    with as_role("api"), tenant_session(tenant) as session, pytest.raises(PermissionDenied):
        trust.approve(session, make_user(tenant, ("recruiter",), step_up=True).actor, proposal.id)


def test_hiring_the_same_candidate_twice_announces_once(tenant):
    ids = make_application(tenant, "interview")
    hire(tenant, ids)
    second = propose_hire(
        tenant, make_user(tenant, ("recruiter",)), ids, "Offer accepted", attempt=2
    )
    approve(tenant, make_user(tenant, ("hr",), step_up=True), second.id)
    run_actions(tenant)
    assert proposal_status(tenant, second.id) == "executed"
    assert len(outbox(tenant, "talent.candidate.hired.v1")) == 1


def test_the_hire_endpoint_checks_the_stage_the_reason_and_the_role(tenant, slug):
    recruiter = signed_in(slug, make_user(tenant, ("recruiter",)))
    applied = make_application(tenant, "applied")["application"]
    url = f"/packs/talent/applications/{applied}/hire"
    assert recruiter.post(url, json={"reason": "Great fit"}).status_code == 409
    shortlisted = make_application(tenant, "shortlisted")["application"]
    url = f"/packs/talent/applications/{shortlisted}/hire"
    assert recruiter.post(url, json={"reason": "no"}).status_code == 422
    assert (
        signed_in(slug, make_user(tenant, ("manager",)))
        .post(url, json={"reason": "Great fit"})
        .status_code
        == 403
    )
    assert (
        recruiter.post(
            f"/packs/talent/applications/{uuid4()}/hire", json={"reason": "Great fit"}
        ).status_code
        == 404
    )


@pytest.mark.xfail(
    strict=True,
    reason="K9: the API role cannot insert proposals, so a person cannot propose over HTTP yet. "
    "See docs/FINANCE_PAYMENT_DESIGN.md. Remove this marker once the kernel allows it.",
)
def test_a_hire_can_be_proposed_over_http(tenant, slug):
    recruiter = signed_in(slug, make_user(tenant, ("recruiter",)))
    application = make_application(tenant, "interview")["application"]
    response = recruiter.post(
        f"/packs/talent/applications/{application}/hire", json={"reason": "Great fit"}
    )
    assert response.status_code == 202


def test_a_hire_flows_from_talent_to_finance_to_an_engagement(tenant, slug):
    """The whole path: approved hire, event, finance notice, HR completes it, engagement draft."""
    ids = make_application(tenant, "interview")
    employee = make_employee(tenant, person_id=ids["person"])
    hire(tenant, ids)
    with as_role("worker"):
        events.relay_once(tenant)

    hr = signed_in(slug, make_user(tenant, ("hr",)))
    [notice] = hr.get("/packs/finance/hire-notices").json()
    assert notice["application_id"] == str(ids["application"])
    assert notice["person_id"] == str(ids["person"])
    assert notice["status"] == "awaiting_terms"

    body = {
        "type": "CDI",
        "starts_on": "2026-12-01",
        "job_title": "Backend Engineer",
        "weekly_hours": "40",
    }
    done = hr.post(f"/packs/finance/hire-notices/{notice['id']}/engagement", json=body)
    assert done.status_code == 201
    assert done.json()["employee_id"] == str(employee)
    assert done.json()["status"] == "draft"
    assert done.json()["pay_items"] is None
    [after] = hr.get("/packs/finance/hire-notices").json()
    assert (after["status"], after["engagement_id"]) == ("converted", done.json()["id"])
