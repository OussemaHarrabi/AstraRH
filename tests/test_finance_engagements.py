"""Engagements, documents, issues, activation, amendments and the hire flow, over real HTTP and
the real database roles."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from conftest import TEST_PASSWORD, as_role, make_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from finance_helpers import make_employee
from sqlalchemy import select

from kernel import events, registry, trust, web
from kernel.db import global_session, tenant_session
from kernel.errors import Conflict, PermissionDenied, ValidationFailed
from kernel.events.models import EventOutbox
from kernel.identity.models import Tenant
from kernel.trust.models import Proposal
from packs.finance import api, consumers, engagements  # noqa: F401 - registers the consumer
from packs.finance.models import (
    DocumentRef,
    Engagement,
    EngagementAmendment,
    HireNotice,
    PayItem,
)
from packs.talent.events import StageChanged

ROOT = Path(__file__).resolve().parents[1]
BASE = "/packs/finance"
CDI_DOCS = ("identity", "contract")

app = FastAPI()
web.install(app)
app.include_router(api.router, prefix=BASE)


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


def terms(**changes) -> dict:
    body = {
        "type": "CDI",
        "starts_on": "2026-11-01",
        "job_title": "Backend Engineer",
        "weekly_hours": "40",
        "head_of_family": True,
        "children": ["child", "child"],
        "pay_items": [{"code": "BASE_SALARY", "amount": "2000.000", "valid_from": "2026-11-01"}],
    }
    body.update(changes)
    return body


def create(http, employee: UUID, **changes):
    return http.post(f"{BASE}/employees/{employee}/engagements", json=terms(**changes))


def verify_documents(http, engagement_id: str, kinds=CDI_DOCS) -> None:
    for kind in kinds:
        added = http.post(f"{BASE}/engagements/{engagement_id}/documents", json={"doc_type": kind})
        assert added.status_code == 201, added.text
        reviewed = http.post(
            f"{BASE}/documents/{added.json()['id']}/review", json={"decision": "verified"}
        )
        assert reviewed.status_code == 200, reviewed.text


def approved_engagement(tenant, slug) -> tuple[TestClient, UUID, UUID]:
    http = signed_in(slug, make_user(tenant, ("finance",)))
    employee = make_employee(tenant)
    body = create(http, employee).json()
    verify_documents(http, body["id"])
    assert http.get(f"{BASE}/engagements/{body['id']}").json()["status"] == "approved"
    return http, employee, UUID(body["id"])


def propose_activation(tenant, user, engagement_id: UUID) -> Proposal:
    """The worker proposes: the API role cannot insert proposals yet (kernel request K9)."""
    with as_role("worker"), tenant_session(tenant) as session:
        return engagements.request_activation(session, tenant, user.actor, engagement_id)


def approve(tenant, user, proposal_id: UUID) -> None:
    with as_role("api"), tenant_session(tenant) as session:
        trust.approve(session, user.actor, proposal_id)


def run_actions(tenant) -> int:
    with as_role("worker"):
        return registry.run_internal_actions(tenant)


def proposal_status(tenant, proposal_id: UUID) -> str:
    with as_role("worker"), tenant_session(tenant) as session:
        return session.get(Proposal, proposal_id).status


def engagement_row(tenant, engagement_id: UUID) -> Engagement:
    with as_role("worker"), tenant_session(tenant) as session:
        return session.get(Engagement, engagement_id)


def active_engagement(tenant, slug) -> tuple[TestClient, UUID, UUID]:
    http, employee, engagement_id = approved_engagement(tenant, slug)
    maker, approver = make_user(tenant, ("hr",)), make_user(tenant, ("finance",))
    proposal = propose_activation(tenant, maker, engagement_id)
    approve(tenant, approver, proposal.id)
    assert run_actions(tenant) == 1
    assert engagement_row(tenant, engagement_id).status == "active"
    return http, employee, engagement_id


def propose_amendment(tenant, user, engagement_id, field, value, day, reason="Annual review"):
    with as_role("worker"), tenant_session(tenant) as session:
        return engagements.request_amendment(
            session, tenant, user.actor, engagement_id, field, value, day, reason
        )


def test_a_new_engagement_is_a_draft_with_blocking_issues(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    response = create(http, make_employee(tenant))
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["open_issues"] == {"blocking": 2, "review": 0}
    issues = http.get(f"{BASE}/engagements/{body['id']}/issues").json()
    assert {i["field"] for i in issues} == {"documents.identity", "documents.contract"}
    assert all(i["next_action"] and i["owner_role"] for i in issues)


def test_verified_documents_make_it_approved(tenant, slug):
    http, _, engagement_id = approved_engagement(tenant, slug)
    body = http.get(f"{BASE}/engagements/{engagement_id}").json()
    assert body["open_issues"] == {"blocking": 0, "review": 0}
    assert all(item["verified"] for item in body["checklist"])


def test_a_rejected_document_keeps_the_engagement_blocked(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    body = create(http, make_employee(tenant)).json()
    verify_documents(http, body["id"], ["identity"])
    added = http.post(f"{BASE}/engagements/{body['id']}/documents", json={"doc_type": "contract"})
    reviewed = http.post(
        f"{BASE}/documents/{added.json()['id']}/review",
        json={"decision": "rejected", "note": "unsigned"},
    )
    assert reviewed.json()["verification_status"] == "rejected"
    status = http.get(f"{BASE}/engagements/{body['id']}").json()
    assert status["status"] == "draft"
    assert status["open_issues"]["blocking"] == 1


def test_an_unknown_document_type_is_refused(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("hr",)))
    body = create(http, make_employee(tenant), pay_items=[]).json()
    response = http.post(f"{BASE}/engagements/{body['id']}/documents", json={"doc_type": "selfie"})
    assert response.status_code == 422


def test_the_same_request_id_returns_the_same_engagement(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    employee = make_employee(tenant)
    first = create(http, employee, external_request_id="hire-req-1")
    second = create(http, employee, external_request_id="hire-req-1")
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    other = create(http, make_employee(tenant), external_request_id="hire-req-1")
    assert other.status_code == 409
    assert len(http.get(f"{BASE}/engagements").json()) == 1


def test_an_unknown_employee_is_not_found(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    assert create(http, uuid4()).status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "FREELANCE"},
        {"children": ["pet"]},
        {"weekly_hours": "0"},
        {"weekly_hours": "169"},
        {"job_title": ""},
        {"pay_items": [{"code": "BASE_SALARY", "amount": "0", "valid_from": "2026-11-01"}]},
        {"pay_items": [{"code": "BASE_SALARY", "amount": "10.0001", "valid_from": "2026-11-01"}]},
    ],
)
def test_malformed_engagement_requests_are_refused(tenant, slug, changes):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    assert create(http, make_employee(tenant), **changes).status_code == 422


def test_hr_can_create_but_never_sees_or_sets_pay(tenant, slug):
    hr = signed_in(slug, make_user(tenant, ("hr",)))
    employee = make_employee(tenant)
    assert create(hr, employee).status_code == 403
    created = create(hr, employee, pay_items=[])
    assert created.status_code == 201
    assert created.json()["pay_items"] is None
    assert hr.get(f"{BASE}/engagements").json()[0]["pay_items"] is None
    finance = signed_in(slug, make_user(tenant, ("finance",)))
    assert finance.get(f"{BASE}/engagements").json()[0]["pay_items"] == []


def test_finance_adds_the_salary_that_hr_could_not(tenant, slug):
    hr = signed_in(slug, make_user(tenant, ("hr",)))
    finance = signed_in(slug, make_user(tenant, ("finance",)))
    body = create(hr, make_employee(tenant), pay_items=[]).json()
    issues = hr.get(f"{BASE}/engagements/{body['id']}/issues").json()
    assert "NO_BASE_SALARY" in {i["code"] for i in issues if i["status"] == "open"}
    item = {"code": "BASE_SALARY", "amount": "1800.000", "valid_from": "2026-11-01"}
    assert hr.post(f"{BASE}/engagements/{body['id']}/pay-items", json=item).status_code == 403
    added = finance.post(f"{BASE}/engagements/{body['id']}/pay-items", json=item)
    assert added.status_code == 201
    assert added.json()["pay_items"][0]["amount"] == "1800.000"
    issues = finance.get(f"{BASE}/engagements/{body['id']}/issues").json()
    cleared = [i for i in issues if i["code"] == "NO_BASE_SALARY"]
    assert [i["status"] for i in cleared] == ["cleared"]


def test_overlapping_or_empty_pay_periods_are_refused(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    body = create(http, make_employee(tenant)).json()
    overlap = {"code": "BASE_SALARY", "amount": "2500.000", "valid_from": "2027-01-01"}
    assert http.post(f"{BASE}/engagements/{body['id']}/pay-items", json=overlap).status_code == 409
    backwards = {**overlap, "code": "BONUS", "valid_to": "2026-12-31"}
    assert (
        http.post(f"{BASE}/engagements/{body['id']}/pay-items", json=backwards).status_code == 422
    )


@pytest.mark.parametrize(
    ("roles", "status"),
    [
        (("finance",), 200),
        (("hr",), 200),
        (("admin",), 200),
        (("auditor",), 200),
        (("recruiter",), 403),
        (("manager",), 403),
        (("employee",), 403),
    ],
)
def test_who_may_read_engagements(tenant, slug, roles, status):
    maker = signed_in(slug, make_user(tenant, ("finance",)))
    create(maker, make_employee(tenant))
    reader = signed_in(slug, make_user(tenant, roles))
    assert reader.get(f"{BASE}/engagements").status_code == status


def test_the_auditor_reads_everything_but_changes_nothing(tenant, slug):
    maker = signed_in(slug, make_user(tenant, ("finance",)))
    body = create(maker, make_employee(tenant)).json()
    auditor = signed_in(slug, make_user(tenant, ("auditor",)))
    assert auditor.get(f"{BASE}/engagements").json()[0]["pay_items"][0]["amount"] == "2000.000"
    assert auditor.post(f"{BASE}/engagements/{body['id']}/validate").status_code == 403
    assert create(auditor, make_employee(tenant)).status_code == 403


def test_a_cdd_with_an_unlisted_reason_waits_for_a_person(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    body = create(
        http, make_employee(tenant), type="CDD", ends_on="2027-04-30", cdd_reason_code="WHIM"
    ).json()
    verify_documents(http, body["id"])
    state = http.get(f"{BASE}/engagements/{body['id']}").json()
    assert state["status"] == "pending_review"
    review = next(
        i
        for i in http.get(f"{BASE}/engagements/{body['id']}/issues").json()
        if i["status"] == "open"
    )
    assert review["code"] == "CDD_REASON_REVIEW"
    assert review["owner_role"] == "HR_LEGAL"

    short = http.post(f"{BASE}/issues/{review['id']}/resolve", json={"reason": "ok"})
    assert short.status_code == 422
    resolved = http.post(
        f"{BASE}/issues/{review['id']}/resolve",
        json={"reason": "Replacement for a documented long leave, checked by HR"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert http.get(f"{BASE}/engagements/{body['id']}").json()["status"] == "approved"

    again = http.post(f"{BASE}/engagements/{body['id']}/validate").json()
    assert again["status"] == "approved"
    assert (
        http.post(f"{BASE}/issues/{review['id']}/resolve", json={"reason": "again"}).status_code
        == 409
    )


def test_a_blocking_issue_cannot_be_waved_through(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    body = create(http, make_employee(tenant)).json()
    blocking = http.get(f"{BASE}/engagements/{body['id']}/issues").json()[0]
    response = http.post(f"{BASE}/issues/{blocking['id']}/resolve", json={"reason": "it is fine"})
    assert response.status_code == 409
    assert "fix its cause" in response.json()["message"]


def test_validation_reports_status_and_open_issues(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("hr",)))
    body = create(http, make_employee(tenant), pay_items=[]).json()
    result = http.post(f"{BASE}/engagements/{body['id']}/validate").json()
    assert result["status"] == "draft"
    assert {"NO_BASE_SALARY", "DOCUMENT_NOT_VERIFIED"} <= {i["code"] for i in result["issues"]}


def test_validation_announces_counts_only(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    body = create(http, make_employee(tenant)).json()
    with as_role("worker"), tenant_session(tenant) as session:
        rows = session.scalars(
            select(EventOutbox).where(EventOutbox.type == "finance.engagement.validated.v1")
        ).all()
    assert rows
    assert set(rows[0].payload) == {"engagement_id", "status", "blocking", "review"}
    assert rows[0].payload["engagement_id"] == body["id"]


def test_an_engagement_that_is_not_ready_cannot_be_proposed(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    body = create(http, make_employee(tenant)).json()
    user = make_user(tenant, ("hr",))
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Conflict, match="DOCUMENT_NOT_VERIFIED"):
            engagements.request_activation(session, tenant, user.actor, UUID(body["id"]))


def test_activation_needs_a_person_and_then_takes_effect(tenant, slug):
    http, employee, engagement_id = approved_engagement(tenant, slug)
    maker, approver = make_user(tenant, ("hr",)), make_user(tenant, ("finance",))
    proposal = propose_activation(tenant, maker, engagement_id)
    assert (proposal.risk, proposal.status) == ("R2", "pending_approval")
    assert engagement_row(tenant, engagement_id).status == "approved"

    approve(tenant, approver, proposal.id)
    assert run_actions(tenant) == 1
    row = engagement_row(tenant, engagement_id)
    assert (row.status, row.activated_by) == ("active", approver.id)
    assert row.activated_at is not None
    assert proposal_status(tenant, proposal.id) == "executed"
    with as_role("worker"), tenant_session(tenant) as session:
        event = session.scalars(
            select(EventOutbox).where(EventOutbox.type == "finance.engagement.activated.v1")
        ).one()
    assert event.payload == {
        "engagement_id": str(engagement_id),
        "employee_id": str(employee),
        "type": "CDI",
        "starts_on": "2026-11-01",
    }
    assert "2000" not in str(event.payload)


def test_an_unauthorised_person_cannot_approve_an_activation(tenant, slug):
    _, _, engagement_id = approved_engagement(tenant, slug)
    proposal = propose_activation(tenant, make_user(tenant, ("hr",)), engagement_id)
    with as_role("api"), tenant_session(tenant) as session, pytest.raises(PermissionDenied):
        trust.approve(session, make_user(tenant, ("recruiter",)).actor, proposal.id)
    assert engagement_row(tenant, engagement_id).status == "approved"


def test_terms_changed_after_approval_are_not_activated(tenant, slug):
    _, _, engagement_id = approved_engagement(tenant, slug)
    proposal = propose_activation(tenant, make_user(tenant, ("hr",)), engagement_id)
    approve(tenant, make_user(tenant, ("finance",)), proposal.id)
    with as_role("owner"), tenant_session(tenant) as session:
        session.get(Engagement, engagement_id).job_title = "Chief Executive"
    run_actions(tenant)
    assert engagement_row(tenant, engagement_id).status == "approved"
    assert proposal_status(tenant, proposal.id) == "failed"


def test_a_second_activation_request_is_refused_while_one_is_open(tenant, slug):
    _, _, engagement_id = approved_engagement(tenant, slug)
    user = make_user(tenant, ("hr",))
    propose_activation(tenant, user, engagement_id)
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Conflict, match="already has a request"):
            engagements.request_activation(session, tenant, user.actor, engagement_id)


def test_a_rejected_activation_can_be_asked_again(tenant, slug):
    _, _, engagement_id = approved_engagement(tenant, slug)
    user = make_user(tenant, ("hr",))
    first = propose_activation(tenant, user, engagement_id)
    with as_role("api"), tenant_session(tenant) as session:
        trust.reject(session, make_user(tenant, ("finance",)).actor, first.id, "Wrong start date")
    second = propose_activation(tenant, user, engagement_id)
    assert second.id != first.id


def test_the_decision_record_names_what_a_person_decided(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    body = create(
        http, make_employee(tenant), type="CDD", ends_on="2027-04-30", cdd_reason_code="WHIM"
    ).json()
    verify_documents(http, body["id"])
    review = next(
        i
        for i in http.get(f"{BASE}/engagements/{body['id']}/issues").json()
        if i["status"] == "open"
    )
    http.post(f"{BASE}/issues/{review['id']}/resolve", json={"reason": "Confirmed with legal"})
    proposal = propose_activation(tenant, make_user(tenant, ("hr",)), UUID(body["id"]))
    from kernel.explain.models import DecisionRecord

    with as_role("api"), tenant_session(tenant) as session:
        decision = session.get(DecisionRecord, proposal.decision_record_id)
    assert "CDD_REASON_REVIEW: Confirmed with legal" in decision.rationale
    assert any("human decision" in item for item in decision.limits)
    assert "2000" not in decision.rationale


def test_an_active_engagement_is_not_revalidated_or_edited_here(tenant, slug):
    http, _, engagement_id = active_engagement(tenant, slug)
    assert http.post(f"{BASE}/engagements/{engagement_id}/validate").json()["status"] == "active"
    item = {"code": "BONUS", "amount": "100.000", "valid_from": "2026-12-01"}
    assert http.post(f"{BASE}/engagements/{engagement_id}/pay-items", json=item).status_code == 409
    added = http.post(
        f"{BASE}/engagements/{engagement_id}/documents", json={"doc_type": "identity"}
    )
    assert added.status_code == 409


def test_a_pay_change_is_effective_dated_and_keeps_history(tenant, slug):
    _, _, engagement_id = active_engagement(tenant, slug)
    maker, approver = make_user(tenant, ("finance",)), make_user(tenant, ("hr",))
    proposal = propose_amendment(
        tenant, maker, engagement_id, "base_salary", "2400.000", date(2027, 1, 1)
    )
    assert proposal.risk == "R2"
    approve(tenant, approver, proposal.id)
    assert run_actions(tenant) == 1

    with as_role("worker"), tenant_session(tenant) as session:
        items = session.scalars(
            select(PayItem)
            .where(PayItem.engagement_id == engagement_id)
            .order_by(PayItem.valid_from)
        ).all()
        amendment = session.scalars(select(EngagementAmendment)).one()
    assert [(i.amount, i.valid_from, i.valid_to) for i in items] == [
        (Decimal("2000.000"), date(2026, 11, 1), date(2026, 12, 31)),
        (Decimal("2400.000"), date(2027, 1, 1), None),
    ]
    assert (amendment.field, amendment.old_value, amendment.new_value) == (
        "base_salary",
        "2000.000",
        "2400.000",
    )
    assert amendment.actor_id == maker.id
    assert amendment.proposal_id == proposal.id
    assert engagement_row(tenant, engagement_id).status == "active"


def test_other_fields_are_amended_from_a_date(tenant, slug):
    _, _, engagement_id = active_engagement(tenant, slug)
    maker, approver = make_user(tenant, ("hr",)), make_user(tenant, ("finance",))
    for field, value in (("weekly_hours", "35"), ("job_title", "Senior Backend Engineer")):
        proposal = propose_amendment(tenant, maker, engagement_id, field, value, date(2027, 1, 1))
        approve(tenant, approver, proposal.id)
        run_actions(tenant)
    row = engagement_row(tenant, engagement_id)
    assert row.weekly_hours == Decimal("35")
    assert row.job_title == "Senior Backend Engineer"
    with as_role("worker"), tenant_session(tenant) as session:
        history = {
            a.field: (a.old_value, a.new_value)
            for a in session.scalars(select(EngagementAmendment))
        }
    assert history["weekly_hours"] == ("40.00", "35")
    assert history["job_title"] == ("Backend Engineer", "Senior Backend Engineer")


def test_a_second_pay_change_on_the_same_date_is_refused_when_it_runs(tenant, slug):
    _, _, engagement_id = active_engagement(tenant, slug)
    maker, approver = make_user(tenant, ("finance",)), make_user(tenant, ("hr",))
    first = propose_amendment(
        tenant, maker, engagement_id, "base_salary", "2400.000", date(2027, 1, 1)
    )
    second = propose_amendment(
        tenant, maker, engagement_id, "base_salary", "2600.000", date(2027, 1, 1)
    )
    for proposal in (first, second):
        approve(tenant, approver, proposal.id)
    run_actions(tenant)
    statuses = sorted([proposal_status(tenant, first.id), proposal_status(tenant, second.id)])
    assert statuses == ["executed", "failed"]
    with as_role("worker"), tenant_session(tenant) as session:
        assert session.query(PayItem).filter(PayItem.engagement_id == engagement_id).count() == 2


@pytest.mark.parametrize(
    ("field", "value", "day", "reason", "message"),
    [
        ("base_salary", "2400.000", date(2026, 10, 1), "Annual review", "before the engagement"),
        ("base_salary", "-5", date(2027, 1, 1), "Annual review", "not a valid value"),
        ("base_salary", "2400.1234", date(2027, 1, 1), "Annual review", "not a valid value"),
        ("weekly_hours", "0", date(2027, 1, 1), "Annual review", "not a valid value"),
        ("ends_on", "2027-12-31", date(2027, 1, 1), "Annual review", "Only a CDD"),
        ("job_title", "  ", date(2027, 1, 1), "Annual review", "cannot be empty"),
        ("job_title", "Lead", date(2027, 1, 1), "ok", "reason is required"),
        ("cdd_reason_code", "X", date(2027, 1, 1), "Annual review", "cannot be amended"),
    ],
)
def test_bad_amendments_are_refused_before_anyone_is_asked(
    tenant, slug, field, value, day, reason, message
):
    _, _, engagement_id = active_engagement(tenant, slug)
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(ValidationFailed, match=message):
            engagements.request_amendment(
                session,
                tenant,
                make_user(tenant, ("hr",)).actor,
                engagement_id,
                field,
                value,
                day,
                reason,
            )


def test_only_an_active_engagement_is_amended(tenant, slug):
    _, _, engagement_id = approved_engagement(tenant, slug)
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Conflict, match="Only an active engagement"):
            engagements.request_amendment(
                session,
                tenant,
                make_user(tenant, ("hr",)).actor,
                engagement_id,
                "job_title",
                "Lead",
                date(2027, 1, 1),
                "Promotion",
            )


def test_hr_cannot_propose_a_pay_change_over_http(tenant, slug):
    _, _, engagement_id = active_engagement(tenant, slug)
    hr = signed_in(slug, make_user(tenant, ("hr",)))
    body = {
        "field": "base_salary",
        "new_value": "9999.000",
        "effective_from": "2027-01-01",
        "reason": "Because",
    }
    assert hr.post(f"{BASE}/engagements/{engagement_id}/amendments", json=body).status_code == 403


def test_a_hired_candidate_gets_one_notice_however_often_the_event_arrives(tenant):
    application, job = uuid4(), uuid4()
    with as_role("worker"), tenant_session(tenant) as session:
        for stage in ("hired", "hired"):
            events.publish(
                session,
                tenant,
                StageChanged(
                    application_id=application, job_id=job, from_stage="shortlisted", to_stage=stage
                ),
            )
        events.publish(
            session,
            tenant,
            StageChanged(
                application_id=uuid4(), job_id=job, from_stage="applied", to_stage="shortlisted"
            ),
        )
    with as_role("worker"):
        events.relay_once(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        notices = session.scalars(select(HireNotice)).all()
    assert [(n.application_id, n.job_id, n.status) for n in notices] == [
        (application, job, "awaiting_terms")
    ]


def test_hr_completes_a_hire_notice_with_the_employee_and_terms(tenant, slug):
    application = uuid4()
    with as_role("worker"), tenant_session(tenant) as session:
        events.publish(
            session,
            tenant,
            StageChanged(
                application_id=application, job_id=uuid4(), from_stage="offer", to_stage="hired"
            ),
        )
    with as_role("worker"):
        events.relay_once(tenant)
    hr = signed_in(slug, make_user(tenant, ("hr",)))
    waiting = hr.get(f"{BASE}/hire-notices", params={"status": "awaiting_terms"}).json()
    assert [n["application_id"] for n in waiting] == [str(application)]

    employee = make_employee(tenant)
    body = {**terms(pay_items=[]), "employee_id": str(employee)}
    done = hr.post(f"{BASE}/hire-notices/{waiting[0]['id']}/engagement", json=body)
    assert done.status_code == 201
    assert done.json()["employee_id"] == str(employee)
    assert hr.get(f"{BASE}/hire-notices", params={"status": "awaiting_terms"}).json() == []
    notice = hr.get(f"{BASE}/hire-notices").json()[0]
    assert (notice["status"], notice["engagement_id"]) == ("converted", done.json()["id"])
    again = hr.post(f"{BASE}/hire-notices/{waiting[0]['id']}/engagement", json=body)
    assert again.status_code == 409


def test_a_hire_notice_that_does_not_exist_is_not_found(tenant, slug):
    hr = signed_in(slug, make_user(tenant, ("hr",)))
    body = {**terms(pay_items=[]), "employee_id": str(make_employee(tenant))}
    assert hr.post(f"{BASE}/hire-notices/{uuid4()}/engagement", json=body).status_code == 404


def test_finance_documents_and_engagements_are_tenant_scoped(tenant, other_tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    body = create(http, make_employee(tenant)).json()
    verify_documents(http, body["id"], ["identity"])
    with as_role("api"), tenant_session(other_tenant) as session:
        assert session.query(Engagement).count() == 0
        assert session.query(DocumentRef).count() == 0
    assert http.get(f"{BASE}/engagements/{uuid4()}").status_code == 404


@pytest.mark.xfail(
    strict=True,
    reason="K9: the API role cannot insert proposals, so a person cannot propose over HTTP yet. "
    "See docs/FINANCE_PAYMENT_DESIGN.md. Remove this marker once the kernel allows it.",
)
def test_activation_can_be_proposed_over_http(tenant, slug):
    http, _, engagement_id = approved_engagement(tenant, slug)
    assert http.post(f"{BASE}/engagements/{engagement_id}/activate").status_code == 202


@pytest.mark.xfail(
    strict=True,
    reason="K9: the API role cannot insert proposals, so a person cannot propose over HTTP yet. "
    "See docs/FINANCE_PAYMENT_DESIGN.md. Remove this marker once the kernel allows it.",
)
def test_an_amendment_can_be_proposed_over_http(tenant, slug):
    http, _, engagement_id = active_engagement(tenant, slug)
    body = {
        "field": "job_title",
        "new_value": "Lead",
        "effective_from": "2027-01-01",
        "reason": "Promotion",
    }
    assert http.post(f"{BASE}/engagements/{engagement_id}/amendments", json=body).status_code == 202


@pytest.mark.xfail(
    strict=True,
    reason="K7: packs cannot register event consumers through the manifest yet, so the worker "
    "must import the finance consumers by hand in apps/worker/main.py. Remove this marker "
    "once the worker registers them.",
)
def test_the_worker_registers_the_finance_consumers():
    assert "packs.finance.consumers" in (ROOT / "apps/worker/main.py").read_text(encoding="utf-8")
