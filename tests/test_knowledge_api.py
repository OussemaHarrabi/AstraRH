"""HR handling of passed-on questions, answer feedback and policy versions, over real HTTP."""

import pytest
from conftest import TEST_PASSWORD, as_role, declare_action, make_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from kernel import knowledge, web
from kernel.db import global_session, tenant_session
from kernel.events import relay_once
from kernel.identity.models import Tenant
from kernel.knowledge.models import Document, Question, Ticket
from kernel.trust.models import AuditEvent

app = FastAPI()
web.install(app)

LEAVE_V1 = "# Annual leave\nEmployees earn 22 working days of paid annual leave per year."
LEAVE_V2 = "# Annual leave\nEmployees earn 25 working days of paid annual leave per year."


@pytest.fixture(autouse=True)
def actions():
    for action, risk in [
        ("kernel.question.feedback", "R0"),
        ("kernel.ticket.answer", "R1"),
        ("kernel.ticket.close", "R1"),
        ("kernel.document.publish", "R1"),
    ]:
        declare_action(action, risk=risk, channel="internal")


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


def passed_on(tenant, asker, text="Can I carry leave into next year?", status="escalated"):
    """A question the assistant refused, with its ticket, as the worker would leave it."""
    with as_role("worker"), tenant_session(tenant) as session:
        question = Question(
            tenant_id=tenant,
            asker_id=asker.id,
            asker_roles=["employee"],
            text=text,
            status=status,
            refusal_reason="No document covers this",
            answer="You earn 22 days [C1]." if status == "answered" else None,
        )
        session.add(question)
        session.flush()
        ticket = None
        if status == "escalated":
            ticket = Ticket(tenant_id=tenant, question_id=question.id, reason="No document")
            session.add(ticket)
            session.flush()
        return question.id, ticket.id if ticket else None


def test_hr_claims_and_answers_a_passed_on_question(tenant, slug):
    employee = make_user(tenant, roles=("employee",))
    hr, other_hr = make_user(tenant, roles=("hr",)), make_user(tenant, roles=("hr",))
    question_id, ticket_id = passed_on(tenant, employee)
    with as_role("api"):
        desk, colleague, asker = (
            signed_in(slug, hr),
            signed_in(slug, other_hr),
            signed_in(slug, employee),
        )
        queue = desk.get("/knowledge/tickets").json()
        assert [t["id"] for t in queue] == [str(ticket_id)]
        assert desk.post(f"/knowledge/tickets/{ticket_id}/claim").json()["status"] == "claimed"
        assert colleague.post(f"/knowledge/tickets/{ticket_id}/claim").status_code == 409
        refused = colleague.post(f"/knowledge/tickets/{ticket_id}/answer", json={"answer": "No."})
        assert refused.status_code == 409
        done = desk.post(
            f"/knowledge/tickets/{ticket_id}/answer",
            json={"answer": "Up to 5 days carry over, until 31 March."},
        )
        assert done.status_code == 200 and done.json()["status"] == "answered"
        seen = asker.get(f"/knowledge/questions/{question_id}").json()
        assert seen["status"] == "answered" and seen["answered_by"] == "hr"
        assert seen["answer"].startswith("Up to 5 days") and seen["citations"] == []
        assert desk.get("/knowledge/tickets").json() == []
        assert len(desk.get("/knowledge/tickets?status=answered").json()) == 1
        again = desk.post(f"/knowledge/tickets/{ticket_id}/answer", json={"answer": "Again"})
        assert again.status_code == 409
    with as_role("api"), tenant_session(tenant) as session:
        audit = session.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == str(hr.id)))
        assert "kernel.ticket.answer" in audit.all()


def test_only_hr_sees_the_ticket_queue(tenant, slug):
    employee = make_user(tenant, roles=("employee",))
    question_id, ticket_id = passed_on(tenant, employee)
    with as_role("api"):
        http = signed_in(slug, employee)
        assert http.get("/knowledge/tickets").status_code == 403
        assert http.get(f"/knowledge/tickets/{ticket_id}").status_code == 403
        assert http.post(f"/knowledge/tickets/{ticket_id}/claim").status_code == 403
        assert http.get("/knowledge/stats").status_code == 403


def test_closing_a_ticket_tells_the_asker_it_is_closed(tenant, slug):
    employee = make_user(tenant, roles=("employee",))
    question_id, ticket_id = passed_on(tenant, employee, text="asdf")
    with as_role("api"):
        desk = signed_in(slug, make_user(tenant, roles=("hr",)))
        closed = desk.post(
            f"/knowledge/tickets/{ticket_id}/close", json={"reason": "Not a question"}
        )
        assert closed.json()["status"] == "closed"
        seen = signed_in(slug, employee).get(f"/knowledge/questions/{question_id}").json()
        assert seen["status"] == "closed"


def test_an_unhelpful_answer_goes_to_hr_once(tenant, slug):
    employee = make_user(tenant, roles=("employee",))
    question_id, _ = passed_on(tenant, employee, status="answered")
    with as_role("api"):
        http = signed_in(slug, employee)
        first = http.post(
            f"/knowledge/questions/{question_id}/feedback",
            json={"helpful": False, "comment": "I am part time"},
        ).json()
        second = http.post(
            f"/knowledge/questions/{question_id}/feedback", json={"helpful": False}
        ).json()
        assert first["ticket_id"] and first["ticket_id"] == second["ticket_id"]
        assert first["feedback"] == {"helpful": False, "comment": "I am part time"}
        stranger = signed_in(slug, make_user(tenant, roles=("employee",)))
        assert (
            stranger.post(
                f"/knowledge/questions/{question_id}/feedback", json={"helpful": True}
            ).status_code
            == 404
        )
        desk = signed_in(slug, make_user(tenant, roles=("hr",)))
        ticket = desk.get(f"/knowledge/tickets/{first['ticket_id']}").json()
        assert "part time" in ticket["reason"]
        assert ticket["assistant_answer"] == "You earn 22 days [C1]."
        stats = desk.get("/knowledge/stats").json()
        assert stats["not_helpful"] == 1 and stats["tickets"] == {"open": 1}


def test_feedback_needs_an_answer(tenant, slug):
    employee = make_user(tenant, roles=("employee",))
    question_id, _ = passed_on(tenant, employee)
    with as_role("api"):
        response = signed_in(slug, employee).post(
            f"/knowledge/questions/{question_id}/feedback", json={"helpful": True}
        )
        assert response.status_code == 409


def test_a_new_version_replaces_the_old_one_in_search(tenant):
    with as_role("worker"), tenant_session(tenant) as session:
        first = knowledge.ingest_document(session, tenant, "POL-LEAVE", "Leave", LEAVE_V1)
        knowledge.ingest_document(session, tenant, "POL-LEAVE", "Leave", LEAVE_V2, version="2")
        hits = knowledge.search(session, "How many annual leave days?", ["employee"])
        assert [hit.document_version for hit in hits] == ["2"]
        assert "25 working days" in hits[0].text
        assert session.get(Document, first.id).status == "superseded"


def test_the_database_allows_one_active_version(tenant):
    with as_role("worker"), tenant_session(tenant) as session:
        knowledge.ingest_document(session, tenant, "POL-LEAVE", "Leave", LEAVE_V1)
    with (
        pytest.raises(IntegrityError, match="one_active_version"),
        as_role("worker"),
        tenant_session(tenant) as session,
    ):
        session.add(Document(tenant_id=tenant, external_id="POL-LEAVE", title="Leave", version="9"))
        session.flush()


def test_hr_publishes_a_policy_and_the_worker_indexes_it(tenant, slug):
    hr, employee = make_user(tenant, roles=("hr",)), make_user(tenant, roles=("employee",))
    body = {
        "external_id": "POL-BONUS",
        "title": "Bonus policy",
        "version": "1",
        "effective_date": "2026-11-01",
        "audience_roles": ["hr"],
        "markdown": "# Bonus\nThe yearly bonus is decided in December.",
    }
    with as_role("api"):
        desk, staff = signed_in(slug, hr), signed_in(slug, employee)
        assert staff.post("/knowledge/documents", json=body).status_code == 403
        created = desk.post("/knowledge/documents", json=body)
        assert created.status_code == 202 and created.json()["status"] == "processing"
        assert desk.post("/knowledge/documents", json=body).status_code == 409
        public = desk.post(
            "/knowledge/documents",
            json=body | {"external_id": "POL-DRESS", "title": "Dress code", "audience_roles": []},
        ).json()
        assert staff.get("/knowledge/documents").json() == []
    with as_role("worker"):
        relay_once(tenant)
    with as_role("api"):
        listed = {d["external_id"]: d for d in desk.get("/knowledge/documents").json()}
        assert listed["POL-BONUS"]["status"] == "active" and listed["POL-BONUS"]["sections"] == 1
        assert [d["external_id"] for d in staff.get("/knowledge/documents").json()] == ["POL-DRESS"]
        restricted = listed["POL-BONUS"]["id"]
        assert staff.get(f"/knowledge/documents/{restricted}").status_code == 404
        page = staff.get(f"/knowledge/documents/{public['id']}").json()
        assert page["content"][0]["section"] == "Bonus"
