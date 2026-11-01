"""Payroll runs over real HTTP, the real worker path and the real database roles.

Expected figures were worked out by hand from the demo rule set:
    2,000 head of family, 2 children: net 1,544.727, employer cost 2,341.400
    3,500 head of family, 2 children: net 2,476.157, employer cost 4,097.450
    2,500 (2,000 + 500 bonus) with 100 reimbursed: net 1,962.019, employer cost 3,026.750
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from conftest import TEST_PASSWORD, as_role, make_user, superuser_sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from finance_helpers import (
    demo_definition,
    make_employee,
    paid_employee,
    seed_active_engagement,
    store_rule_set,
)
from sqlalchemy import select, text

from kernel import events, explain, registry, trust, web
from kernel.db import global_session, tenant_session
from kernel.errors import Conflict, PermissionDenied
from kernel.events.models import EventOutbox
from kernel.identity.models import Tenant
from kernel.trust.models import Execution, Proposal
from packs.finance import api, consumers, runs  # noqa: F401 - registers the consumers
from packs.finance.models import (
    PayItem,
    PayrollRun,
    PayrollRunInput,
    Payslip,
    PayslipLine,
)
from packs.finance.payroll import scorer

BASE = "/packs/finance"
NOV = {"period_start": "2026-11-01", "period_end": "2026-11-30", "pay_date": "2026-11-30"}

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


def relay(tenant) -> None:
    with as_role("worker"):
        events.relay_once(tenant)


def setup(tenant, slug):
    """A rule set, a signed-in preparer and the preparer's user."""
    store_rule_set(tenant)
    user = make_user(tenant, ("finance",))
    return signed_in(slug, user), user


def create_run(http, **extra):
    return http.post(f"{BASE}/payroll-runs", json={**NOV, **extra})


def run_of(http, run_id) -> dict:
    return http.get(f"{BASE}/payroll-runs/{run_id}").json()


def calculate(http, tenant, run_id) -> dict:
    assert http.post(f"{BASE}/payroll-runs/{run_id}/calculate").status_code == 202
    relay(tenant)
    return run_of(http, run_id)


def payslips(http, run_id) -> list[dict]:
    return http.get(f"{BASE}/payroll-runs/{run_id}/payslips").json()


def issues(http, run_id, **params) -> list[dict]:
    return http.get(f"{BASE}/payroll-runs/{run_id}/issues", params=params).json()


def codes(http, run_id) -> set[str]:
    return {i["code"] for i in issues(http, run_id, status="open")}


def send_rows(http, rows, **period):
    body = {"period_start": "2026-11-01", "period_end": "2026-11-30", "rows": rows, **period}
    response = http.post(f"{BASE}/input-batches/rows", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def row(emp, kind, day, **values):
    return {"employee": emp, "kind": kind, "effective_date": day, **values}


def one_run(tenant, slug, *employees, batches=()):
    """A calculated run. Each employee is a keyword set for paid_employee."""
    http, user = setup(tenant, slug)
    people = [paid_employee(tenant, **e) for e in employees]
    run = create_run(http, input_batch_ids=list(batches)).json()
    return http, user, people, run


def submit(tenant, user, run_id) -> Proposal:
    """The worker proposes: the API role cannot insert proposals yet (kernel request K9)."""
    with as_role("worker"), tenant_session(tenant) as session:
        return runs.submit_for_approval(session, tenant, user.actor, UUID(str(run_id)))


def approve(tenant, user, proposal_id: UUID) -> None:
    with as_role("api"), tenant_session(tenant) as session:
        trust.approve(session, user.actor, proposal_id)


def run_actions(tenant) -> int:
    with as_role("worker"):
        return registry.run_internal_actions(tenant)


def proposal_status(tenant, proposal_id) -> str:
    with as_role("worker"), tenant_session(tenant) as session:
        return session.get(Proposal, proposal_id).status


def execution_error(tenant, proposal_id) -> str | None:
    with as_role("worker"), tenant_session(tenant) as session:
        return session.scalar(select(Execution.error).where(Execution.proposal_id == proposal_id))


def run_row(tenant, run_id) -> PayrollRun:
    with as_role("worker"), tenant_session(tenant) as session:
        return session.get(PayrollRun, UUID(str(run_id)))


def settled_run(tenant, employee_id, engagement_id, net: str) -> None:
    """An earlier run for October that is already closed, walked through the real status path."""
    with as_role("owner"), tenant_session(tenant) as session:
        earlier = PayrollRun(
            tenant_id=tenant,
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 31),
            pay_date=date(2026, 10, 31),
            regime_id="TN_PRIVATE_NON_AGRI",
        )
        session.add(earlier)
        session.flush()
        session.add(
            Payslip(
                tenant_id=tenant,
                run_id=earlier.id,
                employee_id=employee_id,
                engagement_id=engagement_id,
                gross=Decimal("2000.000"),
                employee_deductions=Decimal("0"),
                income_tax=Decimal("0"),
                solidarity=Decimal("0"),
                net_pay=Decimal(net),
                employer_cost=Decimal("2000.000"),
            )
        )
        session.flush()
        for status in (
            "calculated",
            "approval_pending",
            "approved",
            "payment_pending",
            "paid",
            "closed",
        ):
            session.execute(
                text("UPDATE finance.payroll_run SET status = :s WHERE id = :i"),
                {"s": status, "i": earlier.id},
            )


def test_a_run_is_created_as_a_draft_and_the_same_request_id_returns_it(tenant, slug):
    http, user = setup(tenant, slug)
    first = create_run(http, external_request_id="payroll-2026-11")
    assert first.status_code == 201
    body = first.json()
    assert (body["status"], body["calculation_state"], body["rule_set"]) == ("draft", "idle", None)
    assert body["prepared_by"] == str(user.id)
    assert body["totals"]["payslips"] == "0"
    again = create_run(http, external_request_id="payroll-2026-11")
    assert (again.status_code, again.json()["id"]) == (200, body["id"])
    different = http.post(
        f"{BASE}/payroll-runs",
        json={**NOV, "pay_date": "2026-11-29", "external_request_id": "payroll-2026-11"},
    )
    assert different.status_code == 409


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"period_end": "2026-10-31"}, 422),
        ({"period_start": "2026-10-01"}, 422),
        ({"pay_date": "2026-10-30"}, 422),
        ({"regime_id": ""}, 422),
    ],
)
def test_an_impossible_run_is_refused(tenant, slug, changes, status):
    http, _ = setup(tenant, slug)
    assert create_run(http, **changes).status_code == status


def test_a_period_that_overlaps_another_run_is_refused(tenant, slug):
    http, _ = setup(tenant, slug)
    assert create_run(http).status_code == 201
    overlap = http.post(
        f"{BASE}/payroll-runs",
        json={"period_start": "2026-11-15", "period_end": "2026-12-14", "pay_date": "2026-12-14"},
    )
    assert overlap.status_code == 409
    assert "already covers" in overlap.json()["message"]


def test_a_run_needs_one_active_rule_set_covering_the_whole_period(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    none = create_run(http)
    assert (none.status_code, "No rule set" in none.json()["message"]) == (409, True)
    store_rule_set(tenant, demo_definition(valid_from="2026-11-15"))
    late = create_run(http)
    assert late.status_code == 409
    assert "does not cover the whole period" in late.json()["message"]


def test_input_batches_must_exist_and_sit_inside_the_period(tenant, slug):
    http, _ = setup(tenant, slug)
    _, emp, _ = paid_employee(tenant)
    wide = send_rows(
        http,
        [row(emp, "bonus", "2026-11-20", amount="10")],
        period_start="2026-10-15",
        period_end="2026-11-30",
    )
    outside = create_run(http, input_batch_ids=[wide["id"]])
    assert outside.status_code == 422
    assert (
        create_run(http, input_batch_ids=["00000000-0000-0000-0000-000000000000"]).status_code
        == 404
    )


@pytest.mark.parametrize(
    ("roles", "write", "summary", "detail"),
    [
        (("finance",), 201, 200, 200),
        (("admin",), 201, 200, 200),
        (("auditor",), 403, 200, 200),
        (("hr",), 403, 200, 403),
        (("manager",), 403, 403, 403),
        (("recruiter",), 403, 403, 403),
        (("employee",), 403, 403, 403),
    ],
)
def test_who_may_create_read_and_see_the_detail_of_runs(
    tenant, slug, roles, write, summary, detail
):
    store_rule_set(tenant)
    maker = signed_in(slug, make_user(tenant, ("finance",)))
    run = create_run(maker).json()
    http = signed_in(slug, make_user(tenant, roles))
    other = http.post(
        f"{BASE}/payroll-runs",
        json={"period_start": "2026-12-01", "period_end": "2026-12-31", "pay_date": "2026-12-31"},
    )
    assert other.status_code == write
    assert http.get(f"{BASE}/payroll-runs").status_code == summary
    assert http.get(f"{BASE}/payroll-runs/{run['id']}/payslips").status_code == detail
    assert http.get(f"{BASE}/payroll-runs/{run['id']}/issues").status_code == detail


def test_a_run_needs_a_session():
    assert (
        TestClient(app, base_url="http://testserver").get(f"{BASE}/payroll-runs").status_code == 401
    )


def test_one_employee_is_calculated_to_the_hand_checked_payslip(tenant, slug):
    http, _, [(employee, emp, _)], run = one_run(tenant, slug, {})
    done = calculate(http, tenant, run["id"])
    assert (done["status"], done["calculation_state"], done["calculation_error"]) == (
        "calculated",
        "done",
        None,
    )
    assert done["rule_set"]["is_demo"] is True
    assert "not certified" in done["notice"]
    assert done["totals"] == {
        "payslips": "1",
        "gross": "2000.000",
        "employee_deductions": "193.600",
        "income_tax": "253.683",
        "solidarity": "7.990",
        "net_pay": "1544.727",
        "employer_cost": "2341.400",
    }
    [slip] = payslips(http, run["id"])
    assert (slip["employee"], slip["net_pay"], slip["status"]) == (emp, "1544.727", "draft")
    detail = http.get(f"{BASE}/payslips/{slip['id']}").json()
    assert [(line["code"], line["amount"]) for line in detail["lines"]][:6] == [
        ("GROSS", "2000.000"),
        ("BASE_SALARY", "2000.000"),
        ("CNSS_EMPLOYEE", "193.600"),
        ("IRPP", "253.683"),
        ("CSS", "7.990"),
        ("CNSS_EMPLOYER", "341.400"),
    ]
    assert all(line["rule_ref"].startswith(done["rule_set"]["id"]) for line in detail["lines"])


def test_two_employees_are_totalled_exactly(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {}, {"base_salary": "3500.000"})
    done = calculate(http, tenant, run["id"])
    assert done["totals"] == {
        "payslips": "2",
        "gross": "5500.000",
        "employee_deductions": "532.400",
        "income_tax": "923.962",
        "solidarity": "22.754",
        "net_pay": "4020.884",
        "employer_cost": "6438.850",
    }
    assert sorted(p["net_pay"] for p in payslips(http, run["id"])) == ["1544.727", "2476.157"]


def test_inputs_change_the_payslip_and_are_linked_to_the_run(tenant, slug):
    http, _ = setup(tenant, slug)
    _, emp, _ = paid_employee(tenant)
    batch = send_rows(
        http,
        [
            row(emp, "bonus", "2026-11-20", amount="500"),
            row(emp, "reimbursement", "2026-11-21", amount="100"),
            row(emp, "hours", "2026-11-05", quantity="8"),
        ],
    )
    assert batch["status"] == "ready"
    run = create_run(http, input_batch_ids=[batch["id"]]).json()
    done = calculate(http, tenant, run["id"])
    assert done["totals"]["net_pay"] == "1962.019"
    assert done["totals"]["employer_cost"] == "3026.750"
    assert (done["totals"]["gross"], done["totals"]["employee_deductions"]) == (
        "2500.000",
        "242.000",
    )
    [slip] = payslips(http, run["id"])
    detail = http.get(f"{BASE}/payslips/{slip['id']}").json()
    assert [line["code"] for line in detail["lines"]] == [
        "GROSS",
        "BASE_SALARY",
        "BONUS",
        "CNSS_EMPLOYEE",
        "IRPP",
        "CSS",
        "REIMBURSEMENT",
        "CNSS_EMPLOYER",
    ]
    with as_role("worker"), tenant_session(tenant) as session:
        assert session.query(PayrollRunInput).count() == 3


def test_calculating_again_gives_the_same_results(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {}, {"base_salary": "3500.000"})
    first = calculate(http, tenant, run["id"])
    first_ids = {p["id"] for p in payslips(http, run["id"])}
    hash_before = run_row(tenant, run["id"]).results_hash
    second = calculate(http, tenant, run["id"])
    assert first["totals"] == second["totals"]
    assert run_row(tenant, run["id"]).results_hash == hash_before
    assert {p["id"] for p in payslips(http, run["id"])}.isdisjoint(first_ids)
    assert len(payslips(http, run["id"])) == 2


def test_a_second_calculation_request_is_refused_while_one_waits(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    assert http.post(f"{BASE}/payroll-runs/{run['id']}/calculate").status_code == 202
    assert http.post(f"{BASE}/payroll-runs/{run['id']}/calculate").status_code == 409
    relay(tenant)
    assert run_of(http, run["id"])["status"] == "calculated"


def test_an_employee_employed_for_part_of_the_period_is_flagged_not_paid(tenant, slug):
    http, _, [_, (late, late_emp, _)], run = one_run(
        tenant, slug, {}, {"starts_on": date(2026, 11, 15)}
    )
    done = calculate(http, tenant, run["id"])
    assert done["totals"]["payslips"] == "1"
    [issue] = issues(http, run["id"], status="open")
    assert (issue["code"], issue["severity"], issue["field"]) == (
        "PARTIAL_PERIOD",
        "blocking",
        f"employee:{late}",
    )
    assert late_emp in issue["message"]
    assert done["open_issues"]["blocking"] == 1


def test_a_pay_change_inside_the_period_is_flagged(tenant, slug):
    http, _, [(employee, _, engagement)], run = one_run(tenant, slug, {})
    with as_role("owner"), tenant_session(tenant) as session:
        item = session.scalar(select(PayItem).where(PayItem.engagement_id == engagement))
        item.valid_to = date(2026, 11, 15)
        session.add(
            PayItem(
                tenant_id=tenant,
                engagement_id=engagement,
                code="BASE_SALARY",
                amount=Decimal("2400.000"),
                valid_from=date(2026, 11, 16),
            )
        )
    done = calculate(http, tenant, run["id"])
    assert done["totals"]["payslips"] == "0"
    assert codes(http, run["id"]) == {"PAY_CHANGE_IN_PERIOD"}


def test_an_employee_without_a_base_salary_is_flagged(tenant, slug):
    http, _ = setup(tenant, slug)
    employee = make_employee(tenant)
    seed_active_engagement(tenant, employee)
    run = create_run(http).json()
    done = calculate(http, tenant, run["id"])
    assert (done["totals"]["payslips"], codes(http, run["id"])) == ("0", {"NO_BASE_SALARY"})


def test_a_civp_engagement_is_not_paid_through_payroll(tenant, slug):
    http, _ = setup(tenant, slug)
    employee = make_employee(tenant)
    seed_active_engagement(
        tenant, employee, ends_on=date(2027, 10, 31), base_salary="200.000", type_="CIVP"
    )
    run = create_run(http).json()
    done = calculate(http, tenant, run["id"])
    assert (done["totals"]["payslips"], issues(http, run["id"])) == ("0", [])


def test_two_active_engagements_for_one_employee_are_flagged(tenant, slug):
    http, _, [(employee, _, _)], run = one_run(tenant, slug, {})
    seed_active_engagement(tenant, employee, base_salary="1000.000")
    done = calculate(http, tenant, run["id"])
    assert (done["totals"]["payslips"], codes(http, run["id"])) == ("0", {"MULTIPLE_ENGAGEMENTS"})


def test_an_absence_needs_a_decision_and_the_decision_survives_a_recalculation(tenant, slug):
    http, _ = setup(tenant, slug)
    _, emp, _ = paid_employee(tenant)
    batch = send_rows(http, [row(emp, "absence", "2026-11-12", quantity="2")])
    run = create_run(http, input_batch_ids=[batch["id"]]).json()
    done = calculate(http, tenant, run["id"])
    assert done["totals"]["net_pay"] == "1544.727"
    [issue] = issues(http, run["id"], status="open")
    assert (issue["code"], issue["severity"]) == ("ABSENCE_NOT_PRICED", "review")
    assert "2.000 days" in issue["message"]

    short = http.post(f"{BASE}/issues/{issue['id']}/resolve", json={"reason": "ok"})
    assert short.status_code == 422
    hr = signed_in(slug, make_user(tenant, ("hr",)))
    assert (
        hr.post(f"{BASE}/issues/{issue['id']}/resolve", json={"reason": "Paid leave"}).status_code
        == 403
    )
    done = http.post(
        f"{BASE}/issues/{issue['id']}/resolve", json={"reason": "Paid leave, no deduction"}
    )
    assert done.json()["status"] == "resolved"
    calculate(http, tenant, run["id"])
    assert issues(http, run["id"], status="open") == []
    [kept] = issues(http, run["id"], status="resolved")
    assert kept["resolution_reason"] == "Paid leave, no deduction"


def test_inputs_for_an_employee_who_gets_no_payslip_are_flagged(tenant, slug):
    http, _ = setup(tenant, slug)
    _, emp, _ = paid_employee(tenant, starts_on=date(2026, 11, 15))
    batch = send_rows(http, [row(emp, "hours", "2026-11-20", quantity="8")])
    assert batch["status"] == "ready"
    run = create_run(http, input_batch_ids=[batch["id"]]).json()
    calculate(http, tenant, run["id"])
    assert codes(http, run["id"]) == {"PARTIAL_PERIOD", "INPUT_WITHOUT_PAYSLIP"}


def test_a_batch_that_still_has_open_issues_blocks_the_run(tenant, slug):
    http, _ = setup(tenant, slug)
    _, emp, _ = paid_employee(tenant)
    bonus = {"kind": "bonus", "effective_date": "2026-11-20", "amount": "100"}
    batch = send_rows(
        http,
        [
            {"employee": emp, "reference": "A", **bonus},
            {"employee": emp, "reference": "B", **bonus},
        ],
    )
    assert batch["status"] == "needs_attention"
    run = create_run(http, input_batch_ids=[batch["id"]]).json()
    done = calculate(http, tenant, run["id"])
    assert done["totals"]["payslips"] == "1"
    [issue] = issues(http, run["id"], status="open")
    assert (issue["code"], issue["severity"]) == ("BATCH_NEEDS_ATTENTION", "blocking")
    assert issue["field"] == f"batch:{batch['id']}"


def test_a_big_change_from_the_last_run_needs_a_person(tenant, slug):
    http, _, [(employee, _, engagement)], run = one_run(tenant, slug, {})
    settled_run(tenant, employee, engagement, "1000.000")
    calculate(http, tenant, run["id"])
    [issue] = issues(http, run["id"], status="open")
    assert (issue["code"], issue["severity"]) == ("NET_CHANGE_LARGE", "review")
    assert "1000.000 to 1544.727" in issue["message"]
    assert "54.5 percent" in issue["message"]


def test_a_small_change_from_the_last_run_is_not_flagged(tenant, slug):
    http, _, [(employee, _, engagement)], run = one_run(tenant, slug, {})
    settled_run(tenant, employee, engagement, "1500.000")
    calculate(http, tenant, run["id"])
    assert issues(http, run["id"]) == []


def test_a_rule_set_that_disappears_makes_the_calculation_fail_cleanly(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    assert http.post(f"{BASE}/payroll-runs/{run['id']}/calculate").status_code == 202
    with as_role("owner"), tenant_session(tenant) as session:
        session.execute(text("UPDATE finance.rule_set SET status = 'superseded'"))
    relay(tenant)
    failed = run_of(http, run["id"])
    assert (failed["status"], failed["calculation_state"]) == ("draft", "failed")
    assert "No rule set" in failed["calculation_error"]
    assert http.post(f"{BASE}/payroll-runs/{run['id']}/calculate").status_code == 409
    store_rule_set(tenant)
    assert http.post(f"{BASE}/payroll-runs/{run['id']}/calculate").status_code == 202
    relay(tenant)
    assert run_of(http, run["id"])["status"] == "calculated"


def test_every_payslip_replays_to_the_same_figures(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {}, {"base_salary": "3500.000"})
    calculate(http, tenant, run["id"])
    result = http.post(f"{BASE}/payroll-runs/{run['id']}/verify").json()
    assert result == {
        "payslips": 2,
        "matching": 2,
        "mismatched": [],
        "run_hash_matches": True,
        "verified": True,
    }
    [first, _] = payslips(http, run["id"])
    single = http.post(f"{BASE}/payslips/{first['id']}/verify").json()
    assert (single["match"], single["inputs_intact"]) == (True, True)
    assert (
        Decimal(single["recorded_score"])
        == Decimal(single["recomputed_score"])
        == Decimal(first["net_pay"])
    )


def test_a_payslip_changed_behind_the_scenes_is_caught_by_the_replay(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    [slip] = payslips(http, run["id"])
    superuser_sql("UPDATE finance.payslip SET net_pay = 9999 WHERE id = :i", i=slip["id"])
    result = http.post(f"{BASE}/payroll-runs/{run['id']}/verify").json()
    assert (result["verified"], result["run_hash_matches"], result["mismatched"]) == (
        False,
        False,
        [slip["id"]],
    )
    user = make_user(tenant, ("finance",))
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Conflict, match="no longer match"):
            runs.submit_for_approval(session, tenant, user.actor, UUID(run["id"]))


def test_the_payslip_decision_explains_every_line_and_hides_the_person(tenant, slug):
    http, _, [(employee, emp, _)], run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    [slip] = payslips(http, run["id"])
    finance_user = make_user(tenant, ("finance",))
    hr_user = make_user(tenant, ("hr",))
    record = UUID(slip["decision_record_id"])
    with as_role("api"), tenant_session(tenant) as session:
        shown = explain.why(session, finance_user.actor, record)
        with pytest.raises(PermissionDenied):
            explain.why(session, hr_user.actor, record)
    assert [f["key"] for f in shown["factors"]] == ["GROSS", "CNSS_EMPLOYEE", "IRPP", "CSS"]
    assert sum(Decimal(f["contribution"]) for f in shown["factors"]) == Decimal("1544.727")
    assert any("not certified" in item for item in shown["limits"])
    assert "Name" in shown["not_considered"]
    assert "Test Employee" not in str(shown)


def test_the_scorer_is_deterministic_and_survives_a_round_trip(tenant, slug):
    from packs.finance.payroll import calc, rules

    definition = demo_definition()
    data = calc.PayslipInput(
        Decimal("2500"),
        True,
        ("child", "child"),
        (("BASE_SALARY", "Base", Decimal("2000")), ("BONUS", "Bonus", Decimal("500"))),
        Decimal("100"),
    )
    inputs = scorer.scorer_inputs(definition, data)
    first = scorer.score(inputs)
    assert first.score == Decimal("1962.019")
    assert sum((f.contribution for f in first.factors), Decimal(0)) == first.score
    assert [f.key for f in first.factors] == [
        "GROSS",
        "CNSS_EMPLOYEE",
        "IRPP",
        "CSS",
        "REIMBURSEMENT",
    ]
    import json

    again = scorer.score(json.loads(json.dumps(inputs)))
    assert again == first
    assert (
        rules.parse(inputs["rule_set"]).definition_hash == rules.parse(definition).definition_hash
    )


def test_a_run_with_open_issues_cannot_be_submitted(tenant, slug):
    http, user = setup(tenant, slug)
    _, emp, _ = paid_employee(tenant)
    batch = send_rows(http, [row(emp, "absence", "2026-11-12", quantity="2")])
    run = create_run(http, input_batch_ids=[batch["id"]]).json()
    calculate(http, tenant, run["id"])
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Conflict, match="ABSENCE_NOT_PRICED"):
            runs.submit_for_approval(session, tenant, user.actor, UUID(run["id"]))


def test_a_run_that_is_not_calculated_cannot_be_submitted(tenant, slug):
    http, user, _, run = one_run(tenant, slug, {})
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Conflict, match="not calculated"):
            runs.submit_for_approval(session, tenant, user.actor, UUID(run["id"]))


def test_a_calculated_run_is_approved_by_a_different_person(tenant, slug):
    http, creator, _, run = one_run(tenant, slug, {}, {"base_salary": "3500.000"})
    calculate(http, tenant, run["id"])
    submitter = make_user(tenant, ("finance",))
    approver = make_user(tenant, ("finance",), step_up=True)
    proposal = submit(tenant, submitter, run["id"])
    assert (proposal.risk, proposal.status) == ("R3", "pending_approval")
    waiting = run_of(http, run["id"])
    assert waiting["status"] == "approval_pending"
    assert proposal.payload["results_hash"] == run_row(tenant, run["id"]).results_hash

    approve(tenant, approver, proposal.id)
    assert run_actions(tenant) == 1
    done = run_row(tenant, run["id"])
    assert (done.status, done.approved_by) == ("approved", approver.id)
    assert done.approved_at is not None
    assert proposal_status(tenant, proposal.id) == "executed"
    assert {p["status"] for p in payslips(http, run["id"])} == {"approved"}
    assert run_of(http, run["id"])["totals"]["net_pay"] == "4020.884"
    with as_role("worker"), tenant_session(tenant) as session:
        event = session.scalars(
            select(EventOutbox).where(EventOutbox.type == "finance.payroll.approved.v1")
        ).one()
    assert event.payload == {"run_id": run["id"], "payslips": 2}


def test_the_decision_record_for_the_approval_names_what_a_person_decided(tenant, slug):
    http, _ = setup(tenant, slug)
    _, emp, _ = paid_employee(tenant)
    batch = send_rows(http, [row(emp, "absence", "2026-11-12", quantity="1")])
    run = create_run(http, input_batch_ids=[batch["id"]]).json()
    calculate(http, tenant, run["id"])
    [issue] = issues(http, run["id"], status="open")
    http.post(f"{BASE}/issues/{issue['id']}/resolve", json={"reason": "Sick leave, fully paid"})
    proposal = submit(tenant, make_user(tenant, ("finance",)), run["id"])
    from kernel.explain.models import DecisionRecord

    with as_role("api"), tenant_session(tenant) as session:
        decision = session.get(DecisionRecord, proposal.decision_record_id)
    assert "ABSENCE_NOT_PRICED: Sick leave, fully paid" in decision.rationale
    assert decision.outcome["total_net"] == "1544.727"
    assert "hr" not in decision.view_roles
    assert any("not certified" in item for item in decision.limits)


def test_the_person_who_prepared_the_run_cannot_approve_it(tenant, slug):
    http, creator, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    proposal = submit(tenant, make_user(tenant, ("finance",)), run["id"])
    creator_with_stepup = make_user(tenant, ("finance",), step_up=True)
    with as_role("owner"), tenant_session(tenant) as session:
        session.execute(
            text("UPDATE finance.payroll_run SET prepared_by = :u WHERE id = :i"),
            {"u": creator_with_stepup.id, "i": run["id"]},
        )
    approve(tenant, creator_with_stepup, proposal.id)
    run_actions(tenant)
    assert proposal_status(tenant, proposal.id) == "failed"
    assert run_row(tenant, run["id"]).status == "approval_pending"
    recalled = http.post(f"{BASE}/payroll-runs/{run['id']}/recall")
    assert (recalled.status_code, recalled.json()["status"]) == (200, "draft")


def test_the_requester_of_the_approval_cannot_approve_it_either(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    requester = make_user(tenant, ("finance",), step_up=True)
    proposal = submit(tenant, requester, run["id"])
    with as_role("api"), tenant_session(tenant) as session, pytest.raises(PermissionDenied):
        trust.approve(session, requester.actor, proposal.id)


def test_approving_needs_a_fresh_password_and_a_finance_role(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    proposal = submit(tenant, make_user(tenant, ("finance",)), run["id"])
    with (
        as_role("api"),
        tenant_session(tenant) as session,
        pytest.raises(Exception, match="password"),
    ):
        trust.approve(session, make_user(tenant, ("finance",), step_up=False).actor, proposal.id)
    for roles in (("hr",), ("recruiter",), ("auditor",)):
        with as_role("api"), tenant_session(tenant) as session, pytest.raises(PermissionDenied):
            trust.approve(session, make_user(tenant, roles, step_up=True).actor, proposal.id)
    assert run_row(tenant, run["id"]).status == "approval_pending"


def test_results_changed_after_submission_are_not_approved(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    proposal = submit(tenant, make_user(tenant, ("finance",)), run["id"])
    approve(tenant, make_user(tenant, ("finance",), step_up=True), proposal.id)
    [slip] = payslips(http, run["id"])
    superuser_sql("UPDATE finance.payslip SET net_pay = 5000 WHERE id = :i", i=slip["id"])
    run_actions(tenant)
    assert proposal_status(tenant, proposal.id) == "failed"
    assert "no longer match the calculated results" in execution_error(tenant, proposal.id)
    assert run_row(tenant, run["id"]).status == "approval_pending"


def test_a_decision_record_changed_behind_the_scenes_is_not_approved(tenant, slug):
    """The payslip and the run's hash are untouched, so only the replay can catch this."""
    http, _, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    [slip] = payslips(http, run["id"])
    proposal = submit(tenant, make_user(tenant, ("finance",)), run["id"])
    approve(tenant, make_user(tenant, ("finance",), step_up=True), proposal.id)
    superuser_sql(
        "UPDATE trust.decision_record SET inputs = jsonb_set(inputs, '{gross}', '\"9999.000\"') "
        "WHERE id = :i",
        i=slip["decision_record_id"],
    )
    run_actions(tenant)
    assert proposal_status(tenant, proposal.id) == "failed"
    assert "does not replay" in execution_error(tenant, proposal.id)
    assert run_row(tenant, run["id"]).status == "approval_pending"


def test_a_rejected_run_goes_back_to_draft_and_can_be_calculated_and_sent_again(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    submitter = make_user(tenant, ("finance",))
    first = submit(tenant, submitter, run["id"])
    with as_role("api"), tenant_session(tenant) as session:
        trust.reject(session, make_user(tenant, ("finance",)).actor, first.id, "Wrong bonus")
    relay(tenant)
    reopened = run_of(http, run["id"])
    assert (reopened["status"], reopened["calculation_state"]) == ("draft", "idle")
    with as_role("worker"), tenant_session(tenant) as session:
        assert session.scalars(
            select(EventOutbox).where(EventOutbox.type == "finance.payroll.rejected.v1")
        ).one().payload == {"run_id": run["id"]}
    calculate(http, tenant, run["id"])
    second = submit(tenant, submitter, run["id"])
    assert second.id != first.id
    approve(tenant, make_user(tenant, ("finance",), step_up=True), second.id)
    run_actions(tenant)
    assert run_row(tenant, run["id"]).status == "approved"


def test_a_submission_can_be_recalled_and_sent_again(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    submitter = make_user(tenant, ("finance",))
    first = submit(tenant, submitter, run["id"])
    recalled = http.post(f"{BASE}/payroll-runs/{run['id']}/recall")
    assert recalled.status_code == 200
    assert (recalled.json()["status"], recalled.json()["calculation_state"]) == ("draft", "idle")
    assert proposal_status(tenant, first.id) == "superseded"
    assert http.post(f"{BASE}/payroll-runs/{run['id']}/recall").status_code == 409


def test_a_submitted_run_cannot_be_recalculated_or_have_its_issues_changed(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    submit(tenant, make_user(tenant, ("finance",)), run["id"])
    assert http.post(f"{BASE}/payroll-runs/{run['id']}/calculate").status_code == 409


def test_a_submitted_runs_issues_cannot_be_decided_until_it_is_recalled(tenant, slug):
    http, _ = setup(tenant, slug)
    _, emp, _ = paid_employee(tenant)
    batch = send_rows(http, [row(emp, "absence", "2026-11-12", quantity="1")])
    run = create_run(http, input_batch_ids=[batch["id"]]).json()
    calculate(http, tenant, run["id"])
    [issue] = issues(http, run["id"], status="open")
    http.post(f"{BASE}/issues/{issue['id']}/resolve", json={"reason": "Paid leave"})
    submit(tenant, make_user(tenant, ("finance",)), run["id"])
    other = http.get(f"{BASE}/payroll-runs/{run['id']}/issues").json()[0]
    assert other["status"] == "resolved"
    assert (
        http.post(f"{BASE}/issues/{other['id']}/resolve", json={"reason": "again"}).status_code
        == 409
    )


def test_withdrawing_an_input_makes_a_calculated_run_stale(tenant, slug):
    http, _ = setup(tenant, slug)
    _, emp, _ = paid_employee(tenant)
    batch = send_rows(http, [row(emp, "bonus", "2026-11-20", amount="500")])
    run = create_run(http, input_batch_ids=[batch["id"]]).json()
    calculate(http, tenant, run["id"])
    [bonus] = http.get(f"{BASE}/input-batches/{batch['id']}/rows").json()
    http.post(f"{BASE}/payroll-inputs/{bonus['id']}/withdraw", json={"reason": "Not approved"})
    stale = run_of(http, run["id"])
    assert (stale["status"], stale["calculation_state"]) == ("draft", "idle")
    again = calculate(http, tenant, run["id"])
    assert again["totals"]["net_pay"] == "1544.727"


def test_an_input_of_a_submitted_run_cannot_be_withdrawn(tenant, slug):
    http, _ = setup(tenant, slug)
    _, emp, _ = paid_employee(tenant)
    batch = send_rows(http, [row(emp, "bonus", "2026-11-20", amount="500")])
    run = create_run(http, input_batch_ids=[batch["id"]]).json()
    calculate(http, tenant, run["id"])
    submit(tenant, make_user(tenant, ("finance",)), run["id"])
    [bonus] = http.get(f"{BASE}/input-batches/{batch['id']}/rows").json()
    refused = http.post(f"{BASE}/payroll-inputs/{bonus['id']}/withdraw", json={"reason": "Mistake"})
    assert refused.status_code == 409
    assert "Recall the run" in refused.json()["message"]
    with pytest.raises(Exception, match="used by a submitted payroll run"):
        with as_role("owner"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.payroll_input SET status = 'withdrawn' WHERE id = :i"),
                {"i": bonus["id"]},
            )


def test_calculation_events_carry_no_amounts(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    with as_role("worker"), tenant_session(tenant) as session:
        found = {
            e.type: e.payload
            for e in session.scalars(
                select(EventOutbox).where(EventOutbox.type.like("finance.payroll.calcul%"))
            )
        }
    assert found["finance.payroll.calculation_requested.v1"] == {"run_id": run["id"]}
    assert found["finance.payroll.calculated.v1"] == {
        "run_id": run["id"],
        "payslips": 1,
        "exceptions": 0,
    }
    assert "1544" not in str(found)


def test_runs_payslips_and_issues_are_tenant_scoped(tenant, other_tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    with as_role("api"), tenant_session(other_tenant) as session:
        assert session.query(PayrollRun).count() == 0
        assert session.query(Payslip).count() == 0
        assert session.query(PayslipLine).count() == 0


def test_the_api_cannot_write_payslips_or_calculated_results(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    for statement in (
        "UPDATE finance.payroll_run SET results_hash = 'x' WHERE id = :i",
        "UPDATE finance.payroll_run SET approved_by = gen_random_uuid() WHERE id = :i",
        "UPDATE finance.payroll_run SET pay_date = '2026-12-31' WHERE id = :i",
    ):
        with pytest.raises(Exception, match="Only the worker can change"):
            with as_role("api"), tenant_session(tenant) as session:
                session.execute(text(statement), {"i": run["id"]})
    other = create_run(
        http, period_start="2026-12-01", period_end="2026-12-31", pay_date="2026-12-31"
    ).json()
    with pytest.raises(Exception, match="Only the worker can move a run to calculated"):
        with as_role("api"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.payroll_run SET status = 'calculated' WHERE id = :i"),
                {"i": other["id"]},
            )
    with pytest.raises(Exception, match="permission denied"):
        with as_role("api"), tenant_session(tenant) as session:
            session.execute(text("DELETE FROM finance.payroll_run_input"))


def test_a_run_can_be_submitted_over_http(tenant, slug):
    http, _, _, run = one_run(tenant, slug, {})
    calculate(http, tenant, run["id"])
    assert http.post(f"{BASE}/payroll-runs/{run['id']}/submit").status_code == 202
