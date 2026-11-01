"""Rule sets and the gross-to-net calculator over real HTTP, with the real database roles."""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from conftest import TEST_PASSWORD, as_role, make_user, superuser_sql
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kernel import registry, trust, web
from kernel.db import global_session, tenant_session
from kernel.errors import Conflict, PermissionDenied, ValidationFailed
from kernel.explain.models import DecisionRecord
from kernel.identity.models import Tenant
from kernel.trust.models import Proposal
from packs.finance import api, service
from packs.finance.models import RuleSetRecord
from packs.finance.payroll import rules

ROOT = Path(__file__).resolve().parents[1]
DEMO = json.loads((ROOT / "data/demo/finance/rule_set_tn_2026_demo.json").read_text("utf-8"))
CALC = "/packs/finance/calculator/net"
HEAD_TWO_KIDS = {"gross": "2000", "head_of_family": True, "children": ["child", "child"]}

app = FastAPI()
web.install(app)
app.include_router(api.router, prefix="/packs/finance")


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


def definition(rule_id: str | None = None, **top_level) -> dict:
    result = copy.deepcopy(DEMO)
    result["id"] = rule_id or f"rs-{uuid4().hex[:8]}"
    result.update(top_level)
    return result


def stored(tenant: UUID, data: dict, status: str = "active") -> UUID:
    parsed = rules.parse(data)
    with as_role("owner"), tenant_session(tenant) as session:
        record = RuleSetRecord(
            tenant_id=tenant,
            rule_id=parsed.id,
            version=parsed.version,
            jurisdiction=parsed.jurisdiction,
            status=status,
            valid_from=parsed.valid_from,
            valid_to=parsed.valid_to,
            is_demo=parsed.is_demo,
            source_ref=parsed.source_ref,
            definition=data,
            definition_hash=parsed.definition_hash,
        )
        session.add(record)
        session.flush()
        return record.id


def net_of(response) -> str:
    assert response.status_code == 200, response.text
    return response.json()["totals"]["net_pay"]


def propose(tenant: UUID, user, record_id: UUID) -> Proposal:
    """The worker proposes: the API role cannot insert proposals yet (kernel request K9)."""
    with as_role("worker"), tenant_session(tenant) as session:
        return service.request_activation(session, tenant, user.actor, record_id)


def test_the_calculator_returns_the_hand_checked_payslip(tenant, slug):
    stored(tenant, definition())
    body = signed_in(slug, make_user(tenant, ("finance",))).post(
        CALC, json={**HEAD_TWO_KIDS, "on": "2026-06-01"}
    )
    assert body.status_code == 200
    result = body.json()
    assert result["totals"] == {
        "employee_deductions": "193.600",
        "income_tax": "253.683",
        "solidarity": "7.990",
        "net_pay": "1544.727",
        "employer_cost": "2341.400",
    }
    assert [line["code"] for line in result["lines"]][:4] == [
        "GROSS",
        "CNSS_EMPLOYEE",
        "IRPP",
        "CSS",
    ]
    assert result["working"]["annual_net_taxable"] == "19176.800"
    assert result["lines"][1]["rule_ref"].endswith("#cnss_employee")
    assert result["rule_set"]["is_demo"] is True
    assert "not certified" in result["notice"]
    assert all(isinstance(value, str) for value in result["totals"].values())


def test_the_calculator_refuses_when_no_rule_set_is_in_force(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    response = http.post(CALC, json={**HEAD_TWO_KIDS, "on": "2026-06-01"})
    assert response.status_code == 422
    assert "No rule set is in force" in response.json()["message"]
    stored(tenant, definition())
    assert http.post(CALC, json={**HEAD_TWO_KIDS, "on": "2025-06-01"}).status_code == 422


def test_a_draft_rule_set_is_never_used(tenant, slug):
    stored(tenant, definition(), status="draft")
    http = signed_in(slug, make_user(tenant, ("finance",)))
    assert http.post(CALC, json={**HEAD_TWO_KIDS, "on": "2026-06-01"}).status_code == 422


def test_the_rule_set_in_force_on_the_date_is_used(tenant, slug):
    first = definition("rs-first", valid_to="2026-06-30")
    second = definition("rs-second", valid_from="2026-07-01")
    second["css"]["rate"] = "0.01"
    stored(tenant, first)
    stored(tenant, second)
    http = signed_in(slug, make_user(tenant, ("finance",)))
    assert net_of(http.post(CALC, json={**HEAD_TWO_KIDS, "on": "2026-06-30"})) == "1544.727"
    assert net_of(http.post(CALC, json={**HEAD_TWO_KIDS, "on": "2026-07-01"})) == "1536.736"


def test_overlapping_active_rule_sets_are_refused_not_guessed(tenant, slug):
    stored(tenant, definition("rs-one"))
    stored(tenant, definition("rs-two"))
    http = signed_in(slug, make_user(tenant, ("finance",)))
    response = http.post(CALC, json={**HEAD_TWO_KIDS, "on": "2026-06-01"})
    assert response.status_code == 422
    assert "overlap" in response.json()["message"]


@pytest.mark.parametrize(
    "body",
    [
        {"gross": "0"},
        {"gross": "-100"},
        {"gross": "abc"},
        {"gross": "2000", "children": ["pet"]},
        {"gross": "2000", "children": ["child"] * 21},
        {"gross": "2000.1234"},
    ],
)
def test_bad_calculator_input_is_refused(tenant, slug, body):
    stored(tenant, definition())
    http = signed_in(slug, make_user(tenant, ("finance",)))
    assert http.post(CALC, json={**body, "on": "2026-06-01"}).status_code == 422


@pytest.mark.parametrize(
    ("roles", "allowed"),
    [
        (("finance",), True),
        (("hr",), True),
        (("admin",), True),
        (("auditor",), True),
        (("recruiter",), False),
        (("manager",), False),
        (("employee",), False),
    ],
)
def test_who_may_use_the_calculator(tenant, slug, roles, allowed):
    stored(tenant, definition())
    http = signed_in(slug, make_user(tenant, roles))
    status = http.post(CALC, json={**HEAD_TWO_KIDS, "on": "2026-06-01"}).status_code
    assert status == (200 if allowed else 403)


def test_the_calculator_needs_a_session():
    http = TestClient(app, base_url="http://testserver")
    assert http.post(CALC, json=HEAD_TWO_KIDS).status_code == 401


def test_compare_runs_each_scenario_and_keeps_their_order(tenant, slug):
    stored(tenant, definition())
    http = signed_in(slug, make_user(tenant, ("finance",)))
    response = http.post(
        "/packs/finance/calculator/compare",
        json={
            "on": "2026-06-01",
            "scenarios": [
                {"gross": "2000", "head_of_family": True, "children": ["child", "child"]},
                {"gross": "2000"},
                {"gross": "3500", "head_of_family": True, "children": ["child", "child"]},
            ],
        },
    )
    assert response.status_code == 200
    nets = [item["totals"]["net_pay"] for item in response.json()["scenarios"]]
    assert nets[0] == "1544.727"
    assert nets[2] == "2476.157"
    assert nets[1] != nets[0]


def test_compare_limits_the_number_of_scenarios(tenant, slug):
    stored(tenant, definition())
    http = signed_in(slug, make_user(tenant, ("finance",)))
    many = [{"gross": "1000"}] * 7
    assert (
        http.post("/packs/finance/calculator/compare", json={"scenarios": many}).status_code == 422
    )


def test_finance_can_save_a_draft_but_hr_cannot(tenant, slug):
    data = definition()
    created = signed_in(slug, make_user(tenant, ("finance",))).post(
        "/packs/finance/rule-sets", json={"definition": data}
    )
    assert created.status_code == 201
    assert created.json()["status"] == "draft"
    assert created.json()["is_demo"] is True
    assert (
        signed_in(slug, make_user(tenant, ("hr",)))
        .post("/packs/finance/rule-sets", json={"definition": definition()})
        .status_code
        == 403
    )


def test_a_malformed_or_duplicate_rule_set_is_refused(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    broken = definition()
    broken.pop("css")
    assert http.post("/packs/finance/rule-sets", json={"definition": broken}).status_code == 422
    data = definition("rs-dup")
    assert http.post("/packs/finance/rule-sets", json={"definition": data}).status_code == 201
    assert http.post("/packs/finance/rule-sets", json={"definition": data}).status_code == 409


def test_listing_hides_the_definition_and_detail_shows_it(tenant, slug):
    record_id = stored(tenant, definition("rs-view"), status="draft")
    http = signed_in(slug, make_user(tenant, ("auditor",)))
    listed = http.get("/packs/finance/rule-sets").json()
    assert [item["rule_id"] for item in listed] == ["rs-view"]
    assert "definition" not in listed[0]
    detail = http.get(f"/packs/finance/rule-sets/{record_id}").json()
    assert detail["definition"]["css"]["rate"] == "0.005"
    assert http.get(f"/packs/finance/rule-sets/{uuid4()}").status_code == 404


def test_the_examples_endpoint_reports_each_example(tenant, slug):
    good = stored(tenant, definition(), status="draft")
    bad_data = definition()
    bad_data["examples"][0]["expect"]["net_pay"] = "1500.000"
    bad = stored(tenant, bad_data, status="draft")
    http = signed_in(slug, make_user(tenant, ("finance",)))
    ok = http.post(f"/packs/finance/rule-sets/{good}/test").json()
    assert ok["passed"] is True
    assert ok["count"] == 4
    failed = http.post(f"/packs/finance/rule-sets/{bad}/test").json()
    assert failed["passed"] is False
    assert failed["results"][0]["mismatches"]["net_pay"] == {
        "expected": "1500.000",
        "got": "1544.727",
    }


def test_activation_needs_a_second_person_and_then_takes_effect(tenant, slug):
    first = make_user(tenant, ("finance",), step_up=True)
    second = make_user(tenant, ("finance",), step_up=True)
    record_id = stored(tenant, definition("rs-new"), status="draft")

    proposal = propose(tenant, first, record_id)
    assert (proposal.risk, proposal.status) == ("R3", "pending_approval")
    assert proposal.payload["definition_hash"] == rules.parse(definition("rs-new")).definition_hash

    http = signed_in(slug, first)
    assert http.post(CALC, json={**HEAD_TWO_KIDS, "on": "2026-06-01"}).status_code == 422

    with as_role("api"), tenant_session(tenant) as session, pytest.raises(PermissionDenied):
        trust.approve(session, first.actor, proposal.id)
    with as_role("api"), tenant_session(tenant) as session:
        trust.approve(session, second.actor, proposal.id)

    with as_role("worker"):
        assert registry.run_internal_actions(tenant) == 1
    assert net_of(http.post(CALC, json={**HEAD_TWO_KIDS, "on": "2026-06-01"})) == "1544.727"

    with as_role("api"), tenant_session(tenant) as session:
        record = session.get(RuleSetRecord, record_id)
        assert record.status == "active"
        assert record.approved_by == second.id
        decision = session.get(DecisionRecord, proposal.decision_record_id)
        assert decision.kind == "finance.rules.activation"
        assert any("demo values" in item for item in decision.limits)


def test_the_approver_needs_a_fresh_password_confirmation(tenant):
    requester = make_user(tenant, ("finance",), step_up=True)
    approver = make_user(tenant, ("finance",), step_up=False)
    proposal = propose(tenant, requester, stored(tenant, definition(), status="draft"))
    with (
        as_role("api"),
        tenant_session(tenant) as session,
        pytest.raises(Exception, match="password"),
    ):
        trust.approve(session, approver.actor, proposal.id)


def test_a_rule_set_changed_after_approval_is_not_activated(tenant):
    requester = make_user(tenant, ("finance",), step_up=True)
    approver = make_user(tenant, ("finance",), step_up=True)
    record_id = stored(tenant, definition(), status="draft")
    proposal = propose(tenant, requester, record_id)
    with as_role("api"), tenant_session(tenant) as session:
        trust.approve(session, approver.actor, proposal.id)

    with as_role("owner"), tenant_session(tenant) as session:
        record = session.get(RuleSetRecord, record_id)
        edited = copy.deepcopy(record.definition)
        edited["css"]["rate"] = "0.02"
        record.definition = edited
    with as_role("worker"):
        registry.run_internal_actions(tenant)

    with as_role("worker"), tenant_session(tenant) as session:
        assert session.get(RuleSetRecord, record_id).status == "draft"
        assert session.get(Proposal, proposal.id).status == "failed"


def test_activation_is_refused_when_examples_are_missing_or_wrong(tenant):
    user = make_user(tenant, ("finance",))
    without = definition()
    without.pop("examples")
    wrong = definition()
    wrong["examples"][1]["expect"]["net_pay"] = "2000.000"
    for data, message in ((without, "at least one"), (wrong, "examples fail")):
        record_id = stored(tenant, data, status="draft")
        with as_role("worker"), tenant_session(tenant) as session:
            with pytest.raises(ValidationFailed, match=message):
                service.request_activation(session, tenant, user.actor, record_id)


def test_activation_is_refused_when_it_overlaps_an_active_rule_set(tenant):
    user = make_user(tenant, ("finance",))
    stored(tenant, definition("rs-active"))
    overlapping = stored(tenant, definition("rs-overlap", valid_from="2026-07-01"), status="draft")
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Conflict, match="overlaps"):
            service.request_activation(session, tenant, user.actor, overlapping)


def test_a_following_rule_set_can_be_proposed_and_shows_what_changed(tenant):
    user = make_user(tenant, ("finance",))
    stored(tenant, definition("rs-2026", valid_to="2026-12-31"))
    following = definition("rs-2027", valid_from="2027-01-01", valid_to=None)
    following["css"]["rate"] = "0.01"
    following["examples"] = [
        {
            "name": "single, gross 400",
            "input": {"gross": "400"},
            "expect": {"net_pay": "361.280"},
        }
    ]
    proposal = propose(tenant, user, stored(tenant, following, status="draft"))
    with as_role("api"), tenant_session(tenant) as session:
        decision = session.get(DecisionRecord, proposal.decision_record_id)
        assert "css.rate: 0.005 -> 0.01" in decision.rationale


def test_an_active_rule_set_cannot_be_proposed_again(tenant):
    user = make_user(tenant, ("finance",))
    record_id = stored(tenant, definition(), status="active")
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Conflict, match="not a draft"):
            service.request_activation(session, tenant, user.actor, record_id)


def test_the_api_cannot_change_a_rule_sets_status_directly(tenant):
    record_id = stored(tenant, definition(), status="draft")
    with pytest.raises(Exception, match="permission denied"):
        with as_role("api"), tenant_session(tenant) as session:
            session.get(RuleSetRecord, record_id).status = "active"
            session.flush()


def test_activation_can_be_proposed_over_http(tenant, slug):
    record_id = stored(tenant, definition(), status="draft")
    http = signed_in(slug, make_user(tenant, ("finance",)))
    assert http.post(f"/packs/finance/rule-sets/{record_id}/activate").status_code == 202


def test_a_tampered_active_rule_set_stops_all_calculation(tenant, slug):
    record_id = stored(tenant, definition())
    superuser_sql(
        "UPDATE finance.rule_set SET definition = jsonb_set(definition, '{css,rate}', '\"0.02\"') "
        "WHERE id = :i",
        i=record_id,
    )
    response = signed_in(slug, make_user(tenant, ("finance",))).post(
        CALC, json={**HEAD_TWO_KIDS, "on": "2026-06-01"}
    )
    assert response.status_code == 422
    assert "no longer matches what was approved" in response.json()["message"]


def test_a_rejected_activation_can_be_requested_again(tenant):
    requester = make_user(tenant, ("finance",))
    reviewer = make_user(tenant, ("finance",), step_up=True)
    record_id = stored(tenant, definition(), status="draft")
    first = propose(tenant, requester, record_id)
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Conflict, match="already has a request"):
            service.request_activation(session, tenant, requester.actor, record_id)
    with as_role("api"), tenant_session(tenant) as session:
        trust.reject(session, reviewer.actor, first.id, "Wrong start date")
    second = propose(tenant, requester, record_id)
    assert second.id != first.id
    assert second.status == "pending_approval"


def test_an_expired_activation_request_is_replaced(tenant):
    requester = make_user(tenant, ("finance",))
    record_id = stored(tenant, definition(), status="draft")
    first = propose(tenant, requester, record_id)
    with as_role("owner"), tenant_session(tenant) as session:
        session.get(Proposal, first.id).expires_at = datetime.now(UTC) - timedelta(minutes=1)
    second = propose(tenant, requester, record_id)
    with as_role("worker"), tenant_session(tenant) as session:
        assert session.get(Proposal, first.id).status == "superseded"
        assert session.get(Proposal, second.id).status == "pending_approval"


def test_the_first_rule_set_says_there_is_nothing_to_compare(tenant):
    proposal = propose(
        tenant, make_user(tenant, ("finance",)), stored(tenant, definition(), "draft")
    )
    with as_role("api"), tenant_session(tenant) as session:
        rationale = session.get(DecisionRecord, proposal.decision_record_id).rationale
    assert "nothing to compare with" in rationale
    assert "->" not in rationale


def test_a_change_to_the_end_date_or_demo_flag_is_shown(tenant):
    user = make_user(tenant, ("finance",))
    stored(tenant, definition("rs-a", valid_to="2026-06-30"))
    following = definition("rs-b", valid_from="2026-07-01", valid_to=None, is_demo=False)
    proposal = propose(tenant, user, stored(tenant, following, status="draft"))
    with as_role("api"), tenant_session(tenant) as session:
        rationale = session.get(DecisionRecord, proposal.decision_record_id).rationale
    assert "is_demo: True -> False" in rationale
    assert "valid_to: 2026-06-30 -> None" in rationale


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["css"].update(rate="NaN"),
        lambda d: d["css"].update(rate="Infinity"),
        lambda d: d["css"].update(rate=0.005),
        lambda d: d["professional_expenses"].update(cap_annual=1e20),
        lambda d: d["examples"][0]["input"].update(gross="Infinity"),
    ],
)
def test_non_finite_or_unquoted_numbers_are_refused_not_crashed(tenant, slug, mutate):
    data = definition()
    mutate(data)
    http = signed_in(slug, make_user(tenant, ("finance",)))
    assert http.post("/packs/finance/rule-sets", json={"definition": data}).status_code == 422


def test_today_is_taken_in_tunis_time():
    assert service.today_in_tunis() == (datetime.now(UTC) + timedelta(hours=1)).date()
