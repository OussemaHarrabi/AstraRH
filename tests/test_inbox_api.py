"""The inbox over real HTTP: listing, handled and reopened conversations, and corrections."""

from datetime import timedelta
from uuid import uuid4

import pytest
from conftest import TEST_PASSWORD, as_role, declare_action, make_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from kernel import comms, web
from kernel.comms.models import Classification
from kernel.db import global_session, tenant_session, utcnow
from kernel.events import EventOutbox
from kernel.identity.models import Tenant
from kernel.trust.models import AuditEvent

app = FastAPI()
web.install(app)


@pytest.fixture(autouse=True)
def actions():
    for action in ("kernel.email.handle", "kernel.email.correct", "kernel.email.digest"):
        declare_action(action, risk="R1", channel="internal")


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


def email(tenant, sender, subject, kind="question", needs_human=False, hours_ago=1):
    """An inbound email and its sorting, as the worker would leave them."""
    with as_role("worker"), tenant_session(tenant) as session:
        message = comms.ingest(
            session,
            tenant,
            f"t:{uuid4().hex}",
            "in",
            sender,
            "hr@cds.example.test",
            subject,
            "Hello",
            utcnow() - timedelta(hours=hours_ago),
        )
        session.add(
            Classification(
                tenant_id=tenant,
                message_id=message.id,
                type=kind,
                urgency="high" if needs_human else "normal",
                needs_human=needs_human,
                human_reason="Legal" if needs_human else None,
                summary=f"About {subject}",
                flagged=False,
                flags=[],
            )
        )
        return str(message.id), str(message.thread_id)


@pytest.fixture
def inbox(tenant):
    return {
        "legal": email(tenant, "a@x.test", "Complaint", "legal_or_complaint", True, 1),
        "question": email(tenant, "b@x.test", "Office hours 50%_off", "question", False, 2),
        "spam": email(tenant, "c@x.test", "Win big", "spam", False, 3),
    }


def test_lists_open_conversations_newest_first_with_filters(tenant, slug, inbox):
    with as_role("api"):
        http = signed_in(slug, make_user(tenant, roles=("recruiter",)))
        listed = http.get("/comms/threads").json()
        assert [t["subject"] for t in listed["items"]] == [
            "Complaint",
            "Office hours 50%_off",
            "Win big",
        ]
        first = listed["items"][0]
        assert first["status"] == "open" and first["messages"] == 1
        assert first["latest_inbound"]["sorting"]["type"] == "legal_or_complaint"
        urgent = http.get("/comms/threads?needs_human=true").json()["items"]
        assert [t["id"] for t in urgent] == [inbox["legal"][1]]
        spam = http.get("/comms/threads?type=spam").json()["items"]
        assert [t["id"] for t in spam] == [inbox["spam"][1]]
        assert http.get("/comms/threads?type=bogus").status_code == 422
        found = http.get("/comms/threads", params={"q": "50%_"}).json()["items"]
        assert [t["id"] for t in found] == [inbox["question"][1]]
        assert http.get("/comms/threads", params={"q": "5%o"}).json()["items"] == []
        assert http.get("/comms/threads", params={"q": "C@X"}).json()["items"][0]["subject"] == (
            "Win big"
        )


def test_pages_with_a_cursor(tenant, slug, inbox):
    with as_role("api"):
        http = signed_in(slug, make_user(tenant, roles=("hr",)))
        page = http.get("/comms/threads?limit=2").json()
        assert len(page["items"]) == 2 and page["next_before"]
        rest = http.get("/comms/threads", params={"limit": 2, "before": page["next_before"]})
        assert [t["subject"] for t in rest.json()["items"]] == ["Win big"]
        assert rest.json()["next_before"] is None


def test_handled_conversations_leave_the_open_list_and_reopen_on_reply(tenant, slug, inbox):
    hr = make_user(tenant, roles=("hr",))
    thread_id = inbox["spam"][1]
    with as_role("api"):
        http = signed_in(slug, hr)
        done = http.post(f"/comms/threads/{thread_id}/handled", json={"note": "Spam"})
        assert done.status_code == 200
        assert done.json()["status"] == "handled" and done.json()["handled_by"] == str(hr.id)
        assert http.post(f"/comms/threads/{thread_id}/handled", json={}).status_code == 409
        open_ids = [t["id"] for t in http.get("/comms/threads").json()["items"]]
        assert thread_id not in open_ids
        handled = http.get("/comms/threads?status=handled").json()["items"]
        assert [t["id"] for t in handled] == [thread_id]
        stats = http.get("/comms/stats").json()
        assert stats["threads"] == {"open": 2, "handled": 1}
        assert stats["open_needing_a_person"] == 1 and "spam" in stats["types"]
    email(tenant, "c@x.test", "Re: Win big")
    with as_role("api"):
        assert http.get(f"/comms/threads/{thread_id}").json()["status"] == "open"
        http.post(f"/comms/threads/{thread_id}/handled", json={})
        assert http.post(f"/comms/threads/{thread_id}/reopen").json()["status"] == "open"
        assert http.post(f"/comms/threads/{thread_id}/reopen").status_code == 409
    with as_role("api"), tenant_session(tenant) as session:
        logged = session.scalars(
            select(AuditEvent.action).where(AuditEvent.actor_id == str(hr.id))
        ).all()
        assert logged.count("kernel.email.handle") == 3


def test_a_person_corrects_the_sorting_and_the_model_answer_is_kept(tenant, slug, inbox):
    hr = make_user(tenant, roles=("hr",))
    message_id, thread_id = inbox["question"]
    with as_role("api"):
        http = signed_in(slug, hr)
        corrected = http.put(
            f"/comms/messages/{message_id}/sorting",
            json={"type": "offer_or_salary", "needs_human": True, "reason": "Asks about pay"},
        )
        assert corrected.status_code == 200
        sorting = corrected.json()["sorting"]
        assert sorting["type"] == "offer_or_salary" and sorting["needs_human"]
        assert sorting["human_reason"] == "Asks about pay" and sorting["corrected"]
        assert sorting["model_values"]["type"] == "question"
        again = http.put(
            f"/comms/messages/{message_id}/sorting", json={"type": "other", "needs_human": False}
        ).json()["sorting"]
        assert again["model_values"]["type"] == "question", "the first model answer is kept"
        assert again["human_reason"] is None
        nothing = http.put(f"/comms/messages/{message_id}/sorting", json={"type": "other"})
        assert nothing.status_code == 409
        missing = http.put(f"/comms/messages/{uuid4()}/sorting", json={"type": "other"})
        assert missing.status_code == 404
        digest = http.post("/comms/digest").json()
        item = next(i for i in digest["groups"]["other"] if i["message_id"] == message_id)
        assert item["corrected"] and item["thread_status"] == "open"
        thread = http.get(f"/comms/threads/{thread_id}").json()
        assert thread["messages"][0]["sorting"]["type"] == "other"
    with as_role("api"), tenant_session(tenant) as session:
        events = session.scalars(
            select(EventOutbox)
            .where(EventOutbox.type == "comms.classification.corrected.v1")
            .order_by(EventOutbox.id)
        ).all()
        assert [e.payload["after"]["type"] for e in events] == ["offer_or_salary", "other"]


def test_inbox_is_for_hr_and_recruiters_only(tenant, slug, inbox):
    message_id, thread_id = inbox["legal"]
    with as_role("api"):
        http = signed_in(slug, make_user(tenant, roles=("employee",)))
        assert http.get("/comms/threads").status_code == 403
        assert http.get("/comms/stats").status_code == 403
        assert http.post(f"/comms/threads/{thread_id}/handled", json={}).status_code == 403
        denied = http.put(f"/comms/messages/{message_id}/sorting", json={"type": "spam"})
        assert denied.status_code == 403


def test_another_company_cannot_see_or_touch_the_conversation(tenant, other_tenant, inbox):
    with as_role("owner"), global_session() as session:
        other_slug = session.get(Tenant, other_tenant).slug
    _, thread_id = inbox["legal"]
    with as_role("api"):
        http = signed_in(other_slug, make_user(other_tenant, roles=("hr",)))
        assert http.get("/comms/threads").json()["items"] == []
        assert http.get(f"/comms/threads/{thread_id}").status_code == 404
        assert http.post(f"/comms/threads/{thread_id}/handled", json={}).status_code == 404
