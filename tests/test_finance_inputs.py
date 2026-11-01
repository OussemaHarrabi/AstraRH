"""Payroll inputs over real HTTP and the real database roles: import, rejections, idempotency,
conflicts, the issue workflow and withdrawal."""

from datetime import date
from uuid import UUID, uuid4

import pytest
from conftest import TEST_PASSWORD, as_role, make_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from finance_helpers import external_id_of, make_employee, seed_active_engagement
from sqlalchemy import select

from kernel import web
from kernel.db import global_session, tenant_session
from kernel.events.models import EventOutbox
from kernel.identity.models import Tenant
from packs.finance import api, inputs
from packs.finance.models import PayrollInput, PayrollInputBatch

BASE = "/packs/finance"
PERIOD = {"period_start": "2026-11-01", "period_end": "2026-11-30"}
HEADER = ",".join(inputs.COLUMNS)

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


def worker(tenant, slug) -> tuple[TestClient, str, UUID]:
    """A signed-in finance user and an employee who has an active engagement."""
    http = signed_in(slug, make_user(tenant, ("finance",)))
    employee = make_employee(tenant)
    seed_active_engagement(tenant, employee)
    return http, external_id_of(tenant, employee), employee


def line(emp, kind="hours", day="2026-11-05", quantity="8", amount="", ref="") -> str:
    return f"{emp},{kind},{day},{quantity},{amount},{ref}"


def csv_bytes(*lines: str, header: str = HEADER, newline: str = "\n", bom: bool = False) -> bytes:
    text = newline.join([header, *lines]) + newline
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")


def upload(http, content: bytes, **period):
    return http.post(
        f"{BASE}/input-batches",
        data=period or PERIOD,
        files={"file": ("inputs.csv", content, "text/csv")},
    )


def rows_of(http, batch_id: str, **params) -> list[dict]:
    return http.get(f"{BASE}/input-batches/{batch_id}/rows", params=params).json()


def rejections_of(http, batch_id: str) -> dict[int, str]:
    found = http.get(f"{BASE}/input-batches/{batch_id}/rejections").json()
    return {item["line"]: item["code"] for item in found}


def issues_of(http, batch_id: str, **params) -> list[dict]:
    return http.get(f"{BASE}/input-batches/{batch_id}/issues", params=params).json()


def test_a_csv_is_imported_and_every_row_is_stored(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    content = csv_bytes(
        line(emp, "hours", "2026-11-05", "8", ref="TIME-1"),
        line(emp, "bonus", "2026-11-20", "", "150.500"),
        line(emp, "absence", "2026-11-12", "2"),
    )
    response = upload(http, content)
    assert response.status_code == 201
    batch = response.json()
    assert (batch["status"], batch["accepted"], batch["rejected"]) == ("ready", 3, 0)
    assert batch["open_issues"] == {"blocking": 0, "review": 0, "warning": 0}
    rows = rows_of(http, batch["id"])
    assert [(r["line"], r["employee"], r["kind"]) for r in rows] == [
        (2, emp, "hours"),
        (3, emp, "bonus"),
        (4, emp, "absence"),
    ]
    bonus = next(r for r in rows if r["kind"] == "bonus")
    assert (bonus["amount"], bonus["quantity"]) == ("150.500", None)
    assert next(r for r in rows if r["kind"] == "hours")["reference"] == "TIME-1"


def test_bad_rows_are_rejected_with_their_line_and_reason_and_good_ones_stay(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    content = csv_bytes(
        line(emp),
        line("EMP-NOBODY"),
        line(emp, "overtime"),
        line(emp, day="2026-12-01"),
        line(emp, "bonus", quantity="", amount="-5"),
        line(emp, ref="=HYPERLINK(1)", day="2026-11-06"),
        line(emp, quantity="25", day="2026-11-07"),
        line(emp, day="2026-11-08"),
    )
    batch = upload(http, content).json()
    assert (batch["accepted"], batch["rejected"]) == (2, 6)
    assert rejections_of(http, batch["id"]) == {
        3: "EMPLOYEE_UNKNOWN",
        4: "KIND_UNKNOWN",
        5: "DATE_OUTSIDE_PERIOD",
        6: "AMOUNT_INVALID",
        7: "REFERENCE_INVALID",
        8: "QUANTITY_INVALID",
    }
    rejected = http.get(f"{BASE}/input-batches/{batch['id']}/rejections").json()
    assert rejected[0]["raw"]["employee"] == "EMP-NOBODY"
    assert all(item["message"] for item in rejected)
    assert [r["line"] for r in rows_of(http, batch["id"])] == [2, 9]


def test_a_ragged_row_is_rejected_not_the_whole_file(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    content = csv_bytes(line(emp), f"{emp},hours,2026-11-06,8", line(emp, day="2026-11-07"))
    batch = upload(http, content).json()
    assert (batch["accepted"], batch["rejected"]) == (2, 1)
    assert rejections_of(http, batch["id"]) == {3: "ROW_MALFORMED"}


def test_the_same_file_twice_changes_nothing(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    content = csv_bytes(line(emp), line(emp, "bonus", "2026-11-20", "", "100"))
    first = upload(http, content)
    second = upload(http, content)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert len(http.get(f"{BASE}/input-batches").json()) == 1
    assert len(rows_of(http, first.json()["id"])) == 2


def test_the_same_rows_for_another_period_are_recognised_as_already_imported(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    content = csv_bytes(line(emp), line(emp, "bonus", "2026-11-20", "", "100"))
    upload(http, content)
    again = upload(http, content, period_start="2026-11-01", period_end="2026-12-01").json()
    assert (again["accepted"], again["rejected"], again["status"]) == (0, 2, "empty")
    assert set(rejections_of(http, again["id"]).values()) == {"ALREADY_IMPORTED"}


def test_a_row_sent_in_two_files_is_stored_once(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    shared = line(emp, "bonus", "2026-11-20", "", "100")
    upload(http, csv_bytes(shared))
    second = upload(http, csv_bytes(shared, line(emp, day="2026-11-06"))).json()
    assert (second["accepted"], second["rejected"]) == (1, 1)
    assert rejections_of(http, second["id"]) == {2: "ALREADY_IMPORTED"}
    with as_role("worker"), tenant_session(tenant) as session:
        assert session.query(PayrollInput).count() == 2


def test_an_identical_row_twice_in_one_file_is_stored_once(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    batch = upload(http, csv_bytes(line(emp), line(emp))).json()
    assert (batch["accepted"], batch["rejected"]) == (1, 1)
    assert rejections_of(http, batch["id"]) == {3: "DUPLICATE_IN_FILE"}
    message = http.get(f"{BASE}/input-batches/{batch['id']}/rejections").json()[0]["message"]
    assert "line 2" in message


def test_the_same_reference_twice_is_a_duplicate_even_if_the_value_differs(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    content = csv_bytes(
        line(emp, ref="TIME-9"), line(emp, quantity="6", day="2026-11-06", ref="TIME-9")
    )
    batch = upload(http, content).json()
    assert (batch["accepted"], batch["rejected"]) == (1, 1)
    assert rejections_of(http, batch["id"]) == {3: "DUPLICATE_IN_FILE"}


def test_two_identical_bonuses_with_different_references_both_count_but_need_a_person(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    bonus = {"kind": "bonus", "day": "2026-11-20", "quantity": "", "amount": "100"}
    batch = upload(http, csv_bytes(line(emp, ref="A", **bonus), line(emp, ref="B", **bonus))).json()
    assert (batch["accepted"], batch["status"]) == (2, "needs_attention")
    found = issues_of(http, batch["id"], status="open")
    assert sorted(i["code"] for i in found) == ["POSSIBLE_DUPLICATE", "POSSIBLE_DUPLICATE"]
    assert all(i["severity"] == "review" and i["owner_role"] == "FINANCE" for i in found)


def test_a_byte_order_mark_and_windows_line_endings_are_accepted(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    batch = upload(http, csv_bytes(line(emp), newline="\r\n", bom=True)).json()
    assert (batch["accepted"], batch["rejected"]) == (1, 0)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        (csv_bytes(header="employee,kind,date,qty,amount,reference"), "header must be exactly"),
        (csv_bytes(header=HEADER + ",extra"), "header must be exactly"),
        (b"\x00\x01\x02binary", "not a text CSV"),
        (b"\xff\xfe\xfd", "UTF-8"),
        (csv_bytes('EMP-1,"never closed'), "malformed"),
        (HEADER.encode() + b"\n", "no rows"),
    ],
)
def test_a_file_with_the_wrong_shape_is_refused_as_a_whole(tenant, slug, content, message):
    http, _, _ = worker(tenant, slug)
    response = upload(http, content)
    assert response.status_code == 422
    assert message in response.json()["message"]
    assert http.get(f"{BASE}/input-batches").json() == []


def test_an_oversized_file_or_too_many_rows_are_refused(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    assert upload(http, b"x" * (inputs.MAX_BYTES + 1)).status_code == 422
    many = [line(emp, "bonus", "2026-11-05", "", "1", f"r{n}") for n in range(inputs.MAX_ROWS + 1)]
    response = upload(http, csv_bytes(*many))
    assert response.status_code == 422
    assert "more than" in response.json()["message"]


@pytest.mark.parametrize(
    "period",
    [
        {"period_start": "2026-11-30", "period_end": "2026-11-01"},
        {"period_start": "2026-01-01", "period_end": "2026-12-31"},
    ],
)
def test_an_impossible_period_is_refused(tenant, slug, period):
    http, emp, _ = worker(tenant, slug)
    assert upload(http, csv_bytes(line(emp)), **period).status_code == 422


def test_a_missing_or_malformed_period_is_refused(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    assert upload(http, csv_bytes(line(emp)), period_start="2026-11-01").status_code == 422
    assert (
        upload(http, csv_bytes(line(emp)), period_start="soon", period_end="later").status_code
        == 422
    )


@pytest.mark.parametrize(
    ("roles", "write", "read"),
    [
        (("finance",), 201, 200),
        (("admin",), 201, 200),
        (("auditor",), 403, 200),
        (("hr",), 403, 403),
        (("manager",), 403, 403),
        (("recruiter",), 403, 403),
        (("employee",), 403, 403),
    ],
)
def test_who_may_import_and_who_may_read_inputs(tenant, slug, roles, write, read):
    _, emp, _ = worker(tenant, slug)
    http = signed_in(slug, make_user(tenant, roles))
    assert upload(http, csv_bytes(line(emp))).status_code == write
    assert http.get(f"{BASE}/input-batches").status_code == read


def test_inputs_need_a_session():
    http = TestClient(app, base_url="http://testserver")
    assert http.get(f"{BASE}/input-batches").status_code == 401


def test_an_input_without_an_active_engagement_blocks_the_batch_until_it_has_one(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    employee = make_employee(tenant)
    emp = external_id_of(tenant, employee)
    batch = upload(http, csv_bytes(line(emp))).json()
    assert (batch["status"], batch["open_issues"]["blocking"]) == ("needs_attention", 1)
    [issue] = issues_of(http, batch["id"], status="open")
    assert (issue["code"], issue["severity"], issue["line"]) == (
        "NO_ACTIVE_ENGAGEMENT",
        "blocking",
        2,
    )

    blocked = http.post(f"{BASE}/issues/{issue['id']}/resolve", json={"reason": "it is fine"})
    assert blocked.status_code == 409

    seed_active_engagement(tenant, employee)
    again = http.post(f"{BASE}/input-batches/{batch['id']}/validate").json()
    assert (again["status"], again["open_issues"]["blocking"]) == ("ready", 0)
    assert [i["status"] for i in issues_of(http, batch["id"])] == ["cleared"]


def test_an_engagement_that_has_ended_does_not_cover_a_later_input(tenant, slug):
    http = signed_in(slug, make_user(tenant, ("finance",)))
    employee = make_employee(tenant)
    seed_active_engagement(tenant, employee, date(2026, 1, 1), date(2026, 11, 10))
    emp = external_id_of(tenant, employee)
    batch = upload(http, csv_bytes(line(emp, day="2026-11-10"), line(emp, day="2026-11-11"))).json()
    [issue] = issues_of(http, batch["id"], status="open")
    assert (issue["code"], issue["line"]) == ("NO_ACTIVE_ENGAGEMENT", 3)


def test_a_person_decides_a_review_item_and_the_decision_survives_a_recheck(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    bonus = {"kind": "bonus", "day": "2026-11-20", "quantity": "", "amount": "100"}
    batch = upload(http, csv_bytes(line(emp, ref="A", **bonus), line(emp, ref="B", **bonus))).json()
    first, second = issues_of(http, batch["id"], status="open")

    assert (
        http.post(f"{BASE}/issues/{first['id']}/resolve", json={"reason": "ok"}).status_code == 422
    )
    hr = signed_in(slug, make_user(tenant, ("hr",)))
    assert (
        hr.post(f"{BASE}/issues/{first['id']}/resolve", json={"reason": "I think so"}).status_code
        == 403
    )

    for issue in (first, second):
        done = http.post(
            f"{BASE}/issues/{issue['id']}/resolve", json={"reason": "Two separate team bonuses"}
        )
        assert done.status_code == 200
        assert done.json()["status"] == "resolved"
    assert http.get(f"{BASE}/input-batches/{batch['id']}").json()["status"] == "ready"
    again = http.post(f"{BASE}/input-batches/{batch['id']}/validate").json()
    assert (again["status"], again["open_issues"]["review"]) == ("ready", 0)
    assert {i["status"] for i in issues_of(http, batch["id"])} == {"resolved"}


def test_a_warning_does_not_stop_the_batch(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    batch = upload(http, csv_bytes(line(emp, quantity="13"))).json()
    assert (batch["status"], batch["open_issues"]) == (
        "ready",
        {"blocking": 0, "review": 0, "warning": 1},
    )
    [issue] = issues_of(http, batch["id"], status="open")
    assert (issue["code"], issue["severity"]) == ("LONG_DAY", "warning")


def test_hours_and_an_absence_on_the_same_day_need_a_person(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    batch = upload(http, csv_bytes(line(emp), line(emp, "absence", quantity="1"))).json()
    codes = sorted(i["code"] for i in issues_of(http, batch["id"], status="open"))
    assert codes == ["ABSENCE_AND_HOURS_SAME_DAY"] * 2
    assert batch["status"] == "needs_attention"


def test_withdrawing_inputs_updates_the_monthly_check_and_the_counts(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    days = [line(emp, quantity="11", day=f"2026-11-{n:02d}") for n in range(1, 31)]
    batch = upload(http, csv_bytes(*days)).json()
    assert (batch["accepted"], batch["status"]) == (30, "needs_attention")
    assert batch["open_issues"]["review"] == 30

    rows = rows_of(http, batch["id"])
    for row in rows[:4]:
        withdrawn = http.post(
            f"{BASE}/payroll-inputs/{row['id']}/withdraw", json={"reason": "Not approved after all"}
        )
        assert withdrawn.status_code == 200
        assert withdrawn.json()["status"] == "withdrawn"
    after = http.get(f"{BASE}/input-batches/{batch['id']}").json()
    assert (after["accepted"], after["status"], after["open_issues"]["review"]) == (26, "ready", 0)
    assert len(rows_of(http, batch["id"], status="withdrawn")) == 4


def test_an_input_is_withdrawn_once_with_a_reason_and_only_by_finance(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    batch = upload(http, csv_bytes(line(emp))).json()
    row = rows_of(http, batch["id"])[0]
    url = f"{BASE}/payroll-inputs/{row['id']}/withdraw"
    assert http.post(url, json={"reason": "no"}).status_code == 422
    assert (
        signed_in(slug, make_user(tenant, ("hr",)))
        .post(url, json={"reason": "Mistake"})
        .status_code
        == 403
    )
    assert http.post(url, json={"reason": "Entered twice by mistake"}).json()["note"] == (
        "Entered twice by mistake"
    )
    assert http.post(url, json={"reason": "Mistake"}).status_code == 409
    assert (
        http.post(
            f"{BASE}/payroll-inputs/{uuid4()}/withdraw", json={"reason": "Mistake"}
        ).status_code
        == 404
    )


def test_a_withdrawn_row_is_not_imported_again(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    row_line = line(emp)
    first = upload(http, csv_bytes(row_line)).json()
    http.post(
        f"{BASE}/payroll-inputs/{rows_of(http, first['id'])[0]['id']}/withdraw",
        json={"reason": "Wrong week"},
    )
    again = upload(http, csv_bytes(row_line, line(emp, day="2026-11-06"))).json()
    assert rejections_of(http, again["id"]) == {2: "ALREADY_IMPORTED"}


def test_json_rows_use_the_same_checks_and_the_same_content_returns_the_same_batch(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    body = {
        **PERIOD,
        "source": "time",
        "rows": [
            {"employee": emp, "kind": "hours", "effective_date": "2026-11-05", "quantity": "8"},
            {"employee": emp, "kind": "bonus", "effective_date": "2026-11-20", "amount": "-1"},
        ],
    }
    first = http.post(f"{BASE}/input-batches/rows", json=body)
    second = http.post(f"{BASE}/input-batches/rows", json=body)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert (first.json()["accepted"], first.json()["rejected"], first.json()["source"]) == (
        1,
        1,
        "time",
    )
    assert rejections_of(http, first.json()["id"]) == {2: "AMOUNT_INVALID"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["rows"][0].update(quantity=8),
        lambda b: b["rows"][0].update(surprise="x"),
        lambda b: b.update(rows=[]),
        lambda b: b.update(source="somewhere"),
        lambda b: b["rows"][0].update(employee="E" * 65),
    ],
)
def test_malformed_json_rows_are_refused(tenant, slug, mutate):
    http, emp, _ = worker(tenant, slug)
    body = {
        **PERIOD,
        "rows": [
            {"employee": emp, "kind": "hours", "effective_date": "2026-11-05", "quantity": "8"}
        ],
    }
    mutate(body)
    assert http.post(f"{BASE}/input-batches/rows", json=body).status_code == 422


def test_importing_announces_counts_only(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    batch = upload(http, csv_bytes(line(emp, "bonus", "2026-11-20", "", "999.999"))).json()
    with as_role("worker"), tenant_session(tenant) as session:
        events = session.scalars(
            select(EventOutbox).where(EventOutbox.type == "finance.payroll.inputs_validated.v1")
        ).all()
    assert events
    payload = events[-1].payload
    assert set(payload) == {"batch_id", "accepted", "rejected", "blocking", "review", "status"}
    assert payload["batch_id"] == batch["id"]
    assert "999" not in str(payload)


def test_amounts_and_quantities_are_stored_exactly(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    batch = upload(
        http, csv_bytes(line(emp, quantity="7.125"), line(emp, "bonus", "2026-11-20", "", "0.001"))
    ).json()
    rows = {r["kind"]: r for r in rows_of(http, batch["id"])}
    assert rows["hours"]["quantity"] == "7.125"
    assert rows["bonus"]["amount"] == "0.001"


def test_batches_and_rows_are_tenant_scoped(tenant, other_tenant, slug):
    http, emp, _ = worker(tenant, slug)
    batch = upload(http, csv_bytes(line(emp))).json()
    with as_role("api"), tenant_session(other_tenant) as session:
        assert session.query(PayrollInputBatch).count() == 0
        assert session.query(PayrollInput).count() == 0
    assert http.get(f"{BASE}/input-batches/{uuid4()}").status_code == 404
    assert http.get(f"{BASE}/input-batches/{batch['id']}/rows").status_code == 200


def test_the_batch_list_shows_newest_first_with_counts(tenant, slug):
    http, emp, _ = worker(tenant, slug)
    upload(http, csv_bytes(line(emp)))
    second = upload(http, csv_bytes(line(emp, day="2026-11-06"), line("EMP-NOBODY"))).json()
    listed = http.get(f"{BASE}/input-batches").json()
    assert listed[0]["id"] == second["id"]
    assert (listed[0]["accepted"], listed[0]["rejected"]) == (1, 1)
