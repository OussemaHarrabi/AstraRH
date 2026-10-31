"""Authentication, CSRF and the approval flow over real HTTP."""

import pytest
from conftest import TEST_PASSWORD, as_role, declare_action, make_proposal, make_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from kernel import identity, web
from kernel.db import global_session, tenant_session
from kernel.identity.models import Tenant
from kernel.trust.models import Proposal

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


def client() -> TestClient:
    return TestClient(app, base_url="http://testserver", raise_server_exceptions=True)


def login(http, slug, user, password=TEST_PASSWORD):
    return http.post(
        "/auth/login", json={"tenant": slug, "email": user.email, "password": password}
    )


def signed_in(slug, user) -> TestClient:
    http = client()
    assert login(http, slug, user).status_code == 200
    http.headers["x-csrf-token"] = http.cookies[web.CSRF_COOKIE]
    return http


def test_login_sets_httponly_session_cookie(tenant, slug):
    response = login(client(), slug, make_user(tenant))
    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith(web.SESSION_COOKIE))
    assert "HttpOnly" in session_cookie
    assert "SameSite=strict" in session_cookie


def test_wrong_password_and_unknown_email_look_the_same(tenant, slug):
    user = make_user(tenant)
    wrong = login(client(), slug, user, "not the password")
    user.email = "nobody@example.test"
    unknown = login(client(), slug, user)
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_repeated_failures_lock_out(tenant, slug):
    user = make_user(tenant)
    for _ in range(identity.MAX_FAILURES):
        assert login(client(), slug, user, "wrong").status_code == 401
    assert login(client(), slug, user).status_code == 429


def test_requests_without_a_session_are_refused():
    assert client().get("/trust/proposals").status_code == 401


def test_forged_session_is_refused(tenant):
    http = client()
    http.cookies.set(web.SESSION_COOKIE, "forged.token.value")
    assert http.get("/auth/me").status_code == 401


def test_me_returns_roles(tenant, slug):
    http = signed_in(slug, make_user(tenant, roles=("hr", "auditor")))
    body = http.get("/auth/me").json()
    assert body["roles"] == ["auditor", "hr"]
    assert body["step_up_fresh"] is False


def test_state_change_without_csrf_token_is_refused(tenant, slug):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    http = signed_in(slug, user)
    del http.headers["x-csrf-token"]
    response = http.post(f"/trust/proposals/{proposal.id}/approve", json={})
    assert response.status_code == 403
    assert response.json()["message"] == "Missing or invalid CSRF token"
    with tenant_session(tenant) as session:
        assert session.get(Proposal, proposal.id).status == "pending_approval"


def test_approve_edit_flow_over_http(tenant, slug):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    http = signed_in(slug, user)

    listed = http.get("/trust/proposals", params={"status": "pending_approval"}).json()
    assert [p["id"] for p in listed] == [str(proposal.id)]

    approve_url = f"/trust/proposals/{proposal.id}/approve"
    assert http.post(approve_url, json={"reason": "Good"}).status_code == 200
    assert http.get(f"/trust/proposals/{proposal.id}").json()["status"] == "approved"

    edited = http.post(
        f"/trust/proposals/{proposal.id}/edit", json={"payload": {"to": "b@example.test"}}
    )
    assert edited.status_code == 200
    assert edited.json()["status"] == "pending_approval"
    assert http.post(approve_url, json={}).status_code == 200


def test_unauthorized_approver_gets_403(tenant, slug):
    proposal = make_proposal(tenant)
    http = signed_in(slug, make_user(tenant, roles=("employee",)))
    assert http.post(f"/trust/proposals/{proposal.id}/approve", json={}).status_code == 403


def test_user_cannot_see_proposals_outside_their_roles(tenant, slug):
    proposal = make_proposal(tenant)
    http = signed_in(slug, make_user(tenant, roles=("employee",)))
    assert http.get("/trust/proposals").json() == []
    assert http.get(f"/trust/proposals/{proposal.id}").status_code == 404


def test_step_up_unlocks_r3_approval(tenant, slug):
    action = declare_action("test.r3", risk="R3")
    proposal = make_proposal(tenant, action)
    http = signed_in(slug, make_user(tenant))
    url = f"/trust/proposals/{proposal.id}/approve"
    denied = http.post(url, json={})
    assert denied.status_code == 403
    assert denied.json()["error"] == "step_up_required"

    assert http.post("/auth/step-up", json={"password": "wrong"}).status_code == 403
    assert http.post("/auth/step-up", json={"password": TEST_PASSWORD}).status_code == 200
    assert http.post(url, json={}).status_code == 200


def test_audit_requires_a_role_and_verifies(tenant, slug):
    make_proposal(tenant)
    assert (
        signed_in(slug, make_user(tenant, roles=("employee",))).get("/trust/audit").status_code
        == 403
    )
    http = signed_in(slug, make_user(tenant, roles=("auditor",)))
    assert http.get("/trust/audit").json()
    verified = http.post("/trust/audit/verify").json()
    assert verified["ok"] is True
    assert verified["length"] >= 1


def test_explain_endpoint_returns_the_why(tenant, slug):
    proposal = make_proposal(tenant)
    http = signed_in(slug, make_user(tenant))
    body = http.get(f"/explain/{proposal.decision_record_id}").json()
    assert body["rationale"] == "Test rationale"
    assert body["proposal"]["id"] == str(proposal.id)


def test_registry_lists_packs(tenant, slug):
    http = signed_in(slug, make_user(tenant))
    packs = {p["id"] for p in http.get("/registry/packs").json()}
    assert "kernel" in packs


def test_tenant_cannot_be_chosen_by_the_client(tenant, other_tenant, slug):
    """The tenant comes from the signed session, so another tenant's data is unreachable."""
    outsider_proposal = make_proposal(other_tenant)
    http = signed_in(slug, make_user(tenant))
    assert http.get(f"/trust/proposals/{outsider_proposal.id}").status_code == 404


def test_passwords_are_stored_hashed(tenant):
    user = make_user(tenant)
    with as_role("owner"), tenant_session(tenant) as session:
        stored = session.execute(
            text("SELECT password_hash FROM core.user_account WHERE id = :id"), {"id": user.id}
        ).scalar()
    assert stored.startswith("$argon2")
