"""Payment, reconciliation and closing, through the real trust gate, the real executor steps and
the sandbox bank running in-process.

The executor is simulated by calling its own functions under its own database role: approved
proposals run through `trust.execute` with the real adapter, and `poll_bank` turns the bank's
statuses into events. The worker is simulated by relaying the outbox.

Account tokens decide what the sandbox bank does (see apps/bank/main.py):
    ACC-...-FAIL fails, -PART pays half, -REV pays then returns it, -MISMATCH pays 1 less,
    -REFUSE makes the bank refuse the whole batch, any other token is paid in full.
"""

from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from conftest import as_role, make_user, superuser_sql
from fastapi.testclient import TestClient
from finance_helpers import paid_employee, set_destination
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_finance_runs import (
    BASE,
    approve,
    calculate,
    codes,
    create_run,
    execution_error,
    issues,
    one_run,
    proposal_status,
    relay,
    run_actions,
    run_of,
    run_row,
    setup,
    signed_in,
    submit,
)

from apps.bank import main as bank
from apps.executor.main import poll_bank
from kernel import adapters, trust
from kernel.adapters import payments as bank_adapter
from kernel.db import global_session, tenant_session
from kernel.events.models import EventOutbox
from kernel.identity.models import Tenant
from kernel.trust.models import Execution
from packs.finance import payments
from packs.finance.models import (
    PaymentBatch,
    PaymentDestination,
    PaymentLine,
    PaymentStatusEvent,
)


@pytest.fixture
def slug(tenant):
    with as_role("owner"), global_session() as session:
        return session.get(Tenant, tenant).slug


@pytest.fixture(autouse=True)
def api_role():
    with as_role("api"):
        yield


@pytest.fixture(autouse=True)
def sandbox_bank(monkeypatch):
    bank._batches.clear()
    bank._statuses.clear()
    client = TestClient(bank.app)
    monkeypatch.setattr(
        bank_adapter, "_request", lambda method, path, **kw: client.request(method, path, **kw)
    )
    state = {"cursor": 0}
    monkeypatch.setattr(pytest, "bank_state", state, raising=False)


def approved_run(tenant, slug, *employees):
    """A run that has been calculated, submitted and approved by two different people."""
    http, user, people, run = one_run(tenant, slug, *employees)
    calculate(http, tenant, run["id"])
    proposal = submit(tenant, make_user(tenant, ("finance",)), run["id"])
    approve(tenant, make_user(tenant, ("finance",), step_up=True), proposal.id)
    run_actions(tenant)
    assert run_row(tenant, run["id"]).status == "approved"
    return http, run["id"], people


def propose_release(tenant, run_id, requester=None):
    """The worker proposes, because the API role cannot insert proposals yet (kernel request K9)."""
    requester = requester or make_user(tenant, ("finance",))
    with as_role("worker"), tenant_session(tenant) as session:
        return payments.request_release(session, tenant, requester.actor, UUID(str(run_id)))


def send(tenant, proposal) -> str:
    """A second person approves, then the executor sends."""
    approve(tenant, make_user(tenant, ("finance",), step_up=True), proposal.id)
    with as_role("executor"):
        return trust.execute(tenant, proposal.id, adapters.run, channel="external")


def poll(tenant) -> int:
    with as_role("executor"):
        pytest.bank_state["cursor"] = poll_bank(pytest.bank_state["cursor"])
    return pytest.bank_state["cursor"]


def settle(tenant) -> None:
    """The send result reaches the worker, the bank is polled, its statuses reach the worker."""
    relay(tenant)
    poll(tenant)
    relay(tenant)


def release_and_settle(tenant, run_id) -> str:
    proposal = propose_release(tenant, run_id)
    assert send(tenant, proposal) == "succeeded"
    settle(tenant)
    return str(proposal.id)


def line_rows(tenant, run_id) -> list[PaymentLine]:
    with as_role("worker"), tenant_session(tenant) as session:
        return list(
            session.scalars(
                select(PaymentLine)
                .where(PaymentLine.run_id == UUID(str(run_id)))
                .order_by(PaymentLine.amount)
            )
        )


def statuses_of(tenant, run_id) -> list[str]:
    return [row.status for row in line_rows(tenant, run_id)]


def events_of(tenant, type_) -> list[EventOutbox]:
    with as_role("worker"), tenant_session(tenant) as session:
        return list(session.scalars(select(EventOutbox).where(EventOutbox.type == type_)))


def payments_of(http, run_id) -> dict:
    return http.get(f"{BASE}/payroll-runs/{run_id}/payments").json()


# ---------------------------------------------------------------------------- destinations


def test_a_destination_is_recorded_as_a_token_and_shown_masked(tenant, slug):
    http, _ = setup(tenant, slug)
    employee, external, _ = paid_employee(tenant, destination=None)
    put = http.put(
        f"{BASE}/employees/{employee}/payment-destination", json={"token": "ACC-1234-WXYZ9876"}
    )
    assert put.status_code == 200
    assert put.json() == {"employee": external, "destination": "ACC-...9876"}
    listing = http.get(f"{BASE}/payment-destinations").json()
    assert listing == [{"employee": external, "destination": "ACC-...9876"}]
    assert "WXYZ" not in http.get(f"{BASE}/payment-destinations").text


@pytest.mark.parametrize(
    "token",
    ["DE89370400440532013000", "acc-lower0001", "ACC-x", "ACC-ABCD EFGH", "ACC-" + "A" * 41],
)
def test_an_account_number_or_malformed_token_is_refused(tenant, slug, token):
    http, _ = setup(tenant, slug)
    employee, _, _ = paid_employee(tenant, destination=None)
    response = http.put(f"{BASE}/employees/{employee}/payment-destination", json={"token": token})
    assert response.status_code in {422, 400}
    assert http.get(f"{BASE}/payment-destinations").json() == []


def test_a_destination_can_be_changed_and_an_unknown_employee_is_refused(tenant, slug):
    http, _ = setup(tenant, slug)
    employee, external, _ = paid_employee(tenant, destination="ACC-OLD00001")
    http.put(f"{BASE}/employees/{employee}/payment-destination", json={"token": "ACC-NEW00002"})
    assert http.get(f"{BASE}/payment-destinations").json() == [
        {"employee": external, "destination": "ACC-...0002"}
    ]
    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        http.put(
            f"{BASE}/employees/{missing}/payment-destination", json={"token": "ACC-NEW00002"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    ("roles", "write", "read"),
    [(("hr",), 403, 403), (("auditor",), 403, 200), (("employee",), 403, 403)],
)
def test_destinations_are_for_finance_and_admin_only(tenant, slug, roles, write, read):
    employee, _, _ = paid_employee(tenant, destination=None)
    http = signed_in(slug, make_user(tenant, roles))
    put = http.put(
        f"{BASE}/employees/{employee}/payment-destination", json={"token": "ACC-NEW00002"}
    )
    assert put.status_code == write
    assert http.get(f"{BASE}/payment-destinations").status_code == read


def test_the_database_refuses_anything_that_is_not_a_token(tenant):
    employee, _, _ = paid_employee(tenant, destination=None)
    with pytest.raises(DBAPIError, match="payment_destination_token"):
        set_destination(tenant, employee, "DE89370400440532013000")


def test_one_destination_per_employee(tenant):
    employee, _, _ = paid_employee(tenant, destination="ACC-FIRST001")
    with pytest.raises(DBAPIError, match="duplicate key"):
        set_destination(tenant, employee, "ACC-SECOND02")


# ---------------------------------------------------------------------------- lines and release


def test_an_employee_without_a_destination_blocks_the_run_and_the_others_are_unaffected(
    tenant, slug
):
    http, user = setup(tenant, slug)
    paid_employee(tenant)
    _, missing, _ = paid_employee(tenant, destination=None)
    run = create_run(http).json()
    result = calculate(http, tenant, run["id"])
    assert result["status"] == "calculated"
    open_issues = issues(http, run["id"], status="open")
    assert [(i["code"], i["severity"]) for i in open_issues] == [
        ("NO_PAYMENT_DESTINATION", "blocking")
    ]
    assert missing in open_issues[0]["message"]


def test_a_destination_added_later_clears_the_block_after_recalculating(tenant, slug):
    http, user = setup(tenant, slug)
    employee, _, _ = paid_employee(tenant, destination=None)
    run = create_run(http).json()
    calculate(http, tenant, run["id"])
    assert "NO_PAYMENT_DESTINATION" in codes(http, run["id"])
    http.put(f"{BASE}/employees/{employee}/payment-destination", json={"token": "ACC-LATE0001"})
    calculate(http, tenant, run["id"])
    assert "NO_PAYMENT_DESTINATION" not in codes(http, run["id"])


def test_approving_a_run_creates_one_due_line_per_payslip(tenant, slug):
    http, run_id, _ = approved_run(tenant, slug, {}, {"base_salary": "3500.000"})
    lines = line_rows(tenant, run_id)
    assert [(str(line.amount), line.status) for line in lines] == [
        ("1544.727", "due"),
        ("2476.157", "due"),
    ]
    assert all(line.idempotency_key == f"pay:{line.payslip_id}" for line in lines)
    body = payments_of(http, run_id)
    assert body["run_status"] == "approved"
    assert body["release"] == {"state": "none", "release_number": None, "error": None}
    assert "sandbox" in body["notice"].lower()
    assert all(item["destination"].startswith("ACC-...") for item in body["lines"])


def test_a_release_is_an_r3_external_proposal_that_names_each_line(tenant, slug):
    http, run_id, _ = approved_run(tenant, slug, {}, {"base_salary": "3500.000"})
    proposal = propose_release(tenant, run_id)
    assert (proposal.risk, proposal.status, proposal.channel) == (
        "R3",
        "pending_approval",
        "external",
    )
    payload = proposal.payload
    assert (payload["count"], payload["total"], payload["currency"]) == (2, "4020.884", "TND")
    assert payload["release_number"] == 1
    assert {line["amount"] for line in payload["lines"]} == {"1544.727", "2476.157"}
    assert all(line["token"].startswith("ACC-") for line in payload["lines"])
    assert payload["results_hash"] == run_row(tenant, run_id).results_hash
    waiting = payments_of(http, run_id)
    assert waiting["release"]["state"] == "waiting for approval"
    assert waiting["run_status"] == "approved"


def test_nothing_is_sent_until_a_different_person_approves(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {})
    requester = make_user(tenant, ("finance",), step_up=True)
    proposal = propose_release(tenant, run_id, requester)
    with as_role("executor"):
        assert trust.execute(tenant, proposal.id, adapters.run, channel="external") == "skipped"
    assert bank._batches == {}
    with as_role("api"), tenant_session(tenant) as session:
        with pytest.raises(Exception, match="own|requester|different"):
            trust.approve(session, requester.actor, proposal.id)
    assert bank._batches == {}


def test_approving_a_release_needs_a_fresh_password(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {})
    proposal = propose_release(tenant, run_id)
    with as_role("api"), tenant_session(tenant) as session:
        with pytest.raises(Exception, match="password"):
            trust.approve(session, make_user(tenant, ("finance",)).actor, proposal.id)
    assert bank._batches == {}


def test_a_release_pays_every_line_and_the_run_becomes_paid(tenant, slug):
    http, run_id, _ = approved_run(tenant, slug, {}, {"base_salary": "3500.000"})
    release_and_settle(tenant, run_id)
    assert statuses_of(tenant, run_id) == ["paid", "paid"]
    assert run_row(tenant, run_id).status == "paid"
    body = payments_of(http, run_id)
    assert body["run_status"] == "paid"
    assert body["release"]["state"] == "sent"
    assert body["open_issues"] == []
    [batch] = body["batches"]
    assert (batch["release_number"], batch["total"], batch["lines"]) == (1, "4020.884", 2)
    assert batch["provider_ref"].startswith("BANK-")
    assert {p["status"] for p in http.get(f"{BASE}/payroll-runs/{run_id}/payslips").json()} == {
        "paid"
    }


def test_one_release_is_one_batch_at_the_bank(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {}, {})
    release_and_settle(tenant, run_id)
    assert len(bank._batches) == 1
    assert len(bank._statuses) == 2


def test_every_status_is_kept_as_history(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {"destination": "ACC-HIST0001-REV"})
    release_and_settle(tenant, run_id)
    with as_role("worker"), tenant_session(tenant) as session:
        history = [
            (row.status, row.status_seq, row.amount_matches)
            for row in session.scalars(
                select(PaymentStatusEvent).order_by(PaymentStatusEvent.status_seq)
            )
        ]
    assert history == [("paid", 1, True), ("reversed", 2, True)]


def test_a_second_release_while_nothing_is_due_is_refused(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {})
    release_and_settle(tenant, run_id)
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Exception, match="paid|nothing|due"):
            payments.request_release(
                session, tenant, make_user(tenant, ("finance",)).actor, UUID(str(run_id))
            )


def test_a_run_that_is_not_approved_cannot_be_released(tenant, slug):
    http, user = setup(tenant, slug)
    paid_employee(tenant)
    run = create_run(http).json()
    calculate(http, tenant, run["id"])
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Exception, match="calculated"):
            payments.request_release(session, tenant, user.actor, UUID(run["id"]))


def test_a_tampered_payslip_blocks_a_release(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {})
    superuser_sql(
        "UPDATE finance.payroll_run SET results_hash = repeat('0', 64) WHERE id = :i", i=run_id
    )
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Exception, match="no longer match"):
            payments.request_release(
                session, tenant, make_user(tenant, ("finance",)).actor, UUID(str(run_id))
            )


# ---------------------------------------------------------------------------- bank outcomes


def test_a_failed_payment_is_an_open_issue_and_the_run_stays_pending(tenant, slug):
    http, run_id, _ = approved_run(tenant, slug, {}, {"destination": "ACC-BADBANK1-FAIL"})
    release_and_settle(tenant, run_id)
    assert sorted(statuses_of(tenant, run_id)) == ["failed", "paid"]
    assert run_row(tenant, run_id).status == "payment_pending"
    body = payments_of(http, run_id)
    [issue] = body["open_issues"]
    assert issue["code"] == "PAYMENT_FAILED"
    assert "ACCOUNT_CLOSED" in issue["message"]
    failed = next(line for line in body["lines"] if line["status"] == "failed")
    assert failed["failure_reason"] == "ACCOUNT_CLOSED"


def test_a_part_payment_is_reported_and_never_counted_as_paid(tenant, slug):
    http, run_id, _ = approved_run(tenant, slug, {"destination": "ACC-HALF0001-PART"})
    release_and_settle(tenant, run_id)
    assert statuses_of(tenant, run_id) == ["part_paid"]
    assert run_row(tenant, run_id).status == "payment_pending"
    assert [i["code"] for i in payments_of(http, run_id)["open_issues"]] == ["PAYMENT_PART_PAID"]


def test_an_amount_that_differs_from_the_approval_is_never_marked_paid(tenant, slug):
    http, run_id, _ = approved_run(tenant, slug, {"destination": "ACC-ODD00001-MISMATCH"})
    release_and_settle(tenant, run_id)
    [line] = line_rows(tenant, run_id)
    assert (line.status, line.failure_reason) == ("submitted", "AMOUNT_MISMATCH")
    assert run_row(tenant, run_id).status == "payment_pending"
    assert [i["code"] for i in payments_of(http, run_id)["open_issues"]] == [
        "PAYMENT_AMOUNT_MISMATCH"
    ]
    with as_role("worker"), tenant_session(tenant) as session:
        recorded = session.scalars(select(PaymentStatusEvent)).one()
    assert recorded.amount_matches is False


def test_a_payment_returned_by_the_bank_reopens_the_run(tenant, slug):
    http, run_id, _ = approved_run(tenant, slug, {"destination": "ACC-BACK0001-REV"})
    release_and_settle(tenant, run_id)
    assert statuses_of(tenant, run_id) == ["reversed"]
    assert run_row(tenant, run_id).status == "payment_pending"
    [issue] = payments_of(http, run_id)["open_issues"]
    assert issue["code"] == "PAYMENT_REVERSED"
    assert "RETURNED_BY_BANK" in issue["message"]


def test_a_batch_the_bank_refuses_changes_nothing_and_can_be_released_again(tenant, slug):
    http, run_id, people = approved_run(tenant, slug, {"destination": "ACC-NOPE0001-REFUSE"})
    proposal = propose_release(tenant, run_id)
    assert send(tenant, proposal) == "failed"
    settle(tenant)
    assert statuses_of(tenant, run_id) == ["due"]
    assert run_row(tenant, run_id).status == "approved"
    assert "refused" in execution_error(tenant, proposal.id)
    body = payments_of(http, run_id)
    assert body["release"]["state"] == "failed"
    assert "refused" in body["release"]["error"]
    assert bank._statuses == []
    employee = people[0][0]
    http.put(f"{BASE}/employees/{employee}/payment-destination", json={"token": "ACC-FIXED001"})
    release_and_settle(tenant, run_id)
    assert statuses_of(tenant, run_id) == ["paid"]
    assert run_row(tenant, run_id).status == "paid"


def test_a_failed_payment_is_retried_with_a_corrected_destination(tenant, slug):
    http, run_id, people = approved_run(tenant, slug, {"destination": "ACC-OLD00001-FAIL"}, {})
    release_and_settle(tenant, run_id)
    assert sorted(statuses_of(tenant, run_id)) == ["failed", "paid"]
    employee = people[0][0]
    assert (
        http.put(
            f"{BASE}/employees/{employee}/payment-destination", json={"token": "ACC-NEW00001"}
        ).status_code
        == 200
    )
    second = propose_release(tenant, run_id)
    assert (second.payload["release_number"], second.payload["count"]) == (2, 1)
    assert second.payload["lines"][0]["token"] == "ACC-NEW00001"
    assert send(tenant, second) == "succeeded"
    settle(tenant)
    assert statuses_of(tenant, run_id) == ["paid", "paid"]
    assert run_row(tenant, run_id).status == "paid"
    body = payments_of(http, run_id)
    assert [b["release_number"] for b in body["batches"]] == [1, 2]
    assert body["open_issues"] == []
    assert len(bank._batches) == 2


def test_a_reversed_payment_is_released_again_and_the_run_closes_up(tenant, slug):
    http, run_id, people = approved_run(tenant, slug, {"destination": "ACC-RET00001-REV"})
    release_and_settle(tenant, run_id)
    http.put(f"{BASE}/employees/{people[0][0]}/payment-destination", json={"token": "ACC-OK000001"})
    release_and_settle(tenant, run_id)
    assert statuses_of(tenant, run_id) == ["paid"]
    assert run_row(tenant, run_id).status == "paid"
    assert payments_of(http, run_id)["open_issues"] == []


def test_a_destination_cannot_be_used_for_a_line_already_in_flight(tenant, slug):
    _, run_id, people = approved_run(tenant, slug, {})
    release_and_settle(tenant, run_id)
    [line] = line_rows(tenant, run_id)
    with pytest.raises(DBAPIError, match="cannot"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(
                text(
                    "UPDATE finance.payment_line SET bank_ref_token = 'ACC-HIJACK01' WHERE id = :i"
                ),
                {"i": line.id},
            )


# ---------------------------------------------------------------------------- repetition and order


def test_the_same_status_delivered_twice_is_applied_once(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {})
    release_and_settle(tenant, run_id)
    with as_role("executor"):
        poll_bank(0)
    relay(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        assert len(list(session.scalars(select(PaymentStatusEvent)))) == 1
    assert statuses_of(tenant, run_id) == ["paid"]


def test_a_stale_status_for_an_earlier_release_is_ignored(tenant, slug):
    http, run_id, people = approved_run(tenant, slug, {"destination": "ACC-OLD00002-FAIL"})
    release_and_settle(tenant, run_id)
    http.put(f"{BASE}/employees/{people[0][0]}/payment-destination", json={"token": "ACC-GOOD0002"})
    release_and_settle(tenant, run_id)
    assert statuses_of(tenant, run_id) == ["paid"]
    with as_role("executor"):
        poll_bank(0)
    relay(tenant)
    assert statuses_of(tenant, run_id) == ["paid"]


def test_a_status_that_arrives_before_the_release_is_recorded_is_retried_not_lost(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {})
    proposal = propose_release(tenant, run_id)
    assert send(tenant, proposal) == "succeeded"
    poll(tenant)
    [reported] = events_of(tenant, "bank.payment.status_reported.v1")
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(RuntimeError, match="not recorded"):
            payments.apply_status(session, tenant, reported.payload)
    assert statuses_of(tenant, run_id) == ["due"]
    relay(tenant)
    # Whichever event the bus took first, a status that came early is retried after its backoff.
    superuser_sql("UPDATE core.event_delivery SET next_attempt_at = now() WHERE status = 'pending'")
    relay(tenant)
    assert statuses_of(tenant, run_id) == ["paid"]


def test_a_release_recorded_twice_makes_one_batch(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {}, {})
    proposal = propose_release(tenant, run_id)
    assert send(tenant, proposal) == "succeeded"
    relay(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        execution = session.scalar(select(Execution).where(Execution.proposal_id == proposal.id))
        assert payments.record_release(session, tenant, proposal.id, execution.id) is None
        assert len(list(session.scalars(select(PaymentBatch)))) == 1


def test_an_unknown_line_or_status_from_the_bank_is_refused(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {})
    release_and_settle(tenant, run_id)
    base = {
        "provider_ref": "BANK-X",
        "key": "k",
        "status_seq": 5,
        "amount_matches": True,
        "reason_code": None,
    }
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(LookupError):
            payments.apply_status(
                session,
                tenant,
                {**base, "line_id": "00000000-0000-0000-0000-000000000000", "status": "paid"},
            )
        [line] = line_rows(tenant, run_id)
        with pytest.raises(ValueError):
            payments.apply_status(
                session, tenant, {**base, "line_id": str(line.id), "status": "teleported"}
            )


def test_a_status_for_another_tenants_line_cannot_touch_it(tenant, slug, other_tenant):
    _, run_id, _ = approved_run(tenant, slug, {})
    release_and_settle(tenant, run_id)
    [line] = line_rows(tenant, run_id)
    other = other_tenant
    with as_role("worker"), tenant_session(other) as session:
        with pytest.raises(LookupError):
            payments.apply_status(
                session,
                other,
                {
                    "provider_ref": "BANK-X",
                    "key": "k",
                    "line_id": str(line.id),
                    "status": "reversed",
                    "status_seq": 9,
                    "amount_matches": True,
                    "reason_code": None,
                },
            )
    assert statuses_of(tenant, run_id) == ["paid"]


# ---------------------------------------------------------------------------- the unknown outcome


def test_a_timeout_leaves_the_outcome_unknown_and_a_retry_is_refused(tenant, slug, monkeypatch):
    _, run_id, _ = approved_run(tenant, slug, {})

    def slow(method, path, **kwargs):
        raise httpx.ReadTimeout("no answer")

    monkeypatch.setattr(bank_adapter, "_request", slow)
    proposal = propose_release(tenant, run_id)
    assert send(tenant, proposal) == "unknown"
    relay(tenant)
    assert statuses_of(tenant, run_id) == ["due"]
    assert run_row(tenant, run_id).status == "approved"
    assert proposal_status(tenant, proposal.id) != "executed"
    with as_role("executor"):
        assert trust.execute(tenant, proposal.id, adapters.run, channel="external") == "skipped"


def test_an_unknown_release_is_reconciled_by_key_without_resending(tenant, slug, monkeypatch):
    _, run_id, _ = approved_run(tenant, slug, {})
    original_request = bank_adapter._request

    def slow(method, path, **kwargs):
        raise httpx.ReadTimeout("no answer")

    monkeypatch.setattr(bank_adapter, "_request", slow)
    proposal = propose_release(tenant, run_id)
    assert send(tenant, proposal) == "unknown"
    assert bank._batches == {}

    monkeypatch.setattr(bank_adapter, "_request", original_request)
    with as_role("executor"):
        assert trust.reconcile_stale(tenant, adapters.lookup, older_than=timedelta(0)) == 1
    relay(tenant)
    assert bank._batches == {}
    assert statuses_of(tenant, run_id) == ["due"]


def test_a_crashed_send_is_found_at_the_bank_and_recorded_without_sending_again(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {})
    proposal = propose_release(tenant, run_id)
    approve(tenant, make_user(tenant, ("finance",), step_up=True), proposal.id)
    with as_role("executor"):
        claim = trust._claim(tenant, proposal.id, "external")
        bank_adapter.send(claim["payload"], claim["key"])
    assert len(bank._batches) == 1
    with as_role("executor"):
        from datetime import timedelta

        settled = trust.reconcile_stale(tenant, adapters.lookup, older_than=timedelta(0))
    assert settled == 1
    settle(tenant)
    assert len(bank._batches) == 1
    assert statuses_of(tenant, run_id) == ["paid"]
    assert run_row(tenant, run_id).status == "paid"


# ---------------------------------------------------------------------------- privacy


def test_events_never_carry_a_token_an_amount_or_a_name(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {"destination": "ACC-PRIVATE01"})
    release_and_settle(tenant, run_id)
    names = [
        "finance.payment.submitted.v1",
        "bank.payment.status_reported.v1",
        "finance.payment.reconciled.v1",
    ]
    for name in names:
        found = events_of(tenant, name)
        assert found, name
        blob = " ".join(str(e.payload) for e in found)
        assert "ACC-" not in blob and "1544" not in blob and "Test Employee" not in blob


def test_the_payments_view_and_the_decision_show_no_full_token(tenant, slug):
    http, run_id, _ = approved_run(tenant, slug, {"destination": "ACC-SECRET9999"})
    proposal = propose_release(tenant, run_id)
    body = http.get(f"{BASE}/payroll-runs/{run_id}/payments").text
    assert "SECRET" not in body
    from kernel.explain.models import DecisionRecord

    with as_role("api"), tenant_session(tenant) as session:
        decision = session.get(DecisionRecord, proposal.decision_record_id)
    assert "ACC-" not in decision.rationale and "SECRET" not in str(decision.outcome)
    assert "hr" not in decision.view_roles


@pytest.mark.parametrize(
    ("roles", "status"), [(("auditor",), 200), (("hr",), 403), (("employee",), 403)]
)
def test_who_can_see_the_payments_of_a_run(tenant, slug, roles, status):
    _, run_id, _ = approved_run(tenant, slug, {})
    http = signed_in(slug, make_user(tenant, roles))
    assert http.get(f"{BASE}/payroll-runs/{run_id}/payments").status_code == status


# ---------------------------------------------------------------------------- closing


def paid_run(tenant, slug, *employees):
    http, run_id, people = approved_run(tenant, slug, *employees)
    release_and_settle(tenant, run_id)
    assert run_row(tenant, run_id).status == "paid"
    return http, run_id, people


def propose_close(tenant, run_id):
    with as_role("worker"), tenant_session(tenant) as session:
        return payments.request_close(
            session, tenant, make_user(tenant, ("finance",)).actor, UUID(str(run_id))
        )


def test_a_paid_run_is_closed_by_an_r2_approval_and_never_changes_again(tenant, slug):
    http, run_id, _ = paid_run(tenant, slug, {})
    proposal = propose_close(tenant, run_id)
    assert (proposal.risk, proposal.channel) == ("R2", "internal")
    approve(tenant, make_user(tenant, ("finance",)), proposal.id)
    assert run_actions(tenant) == 1
    assert run_row(tenant, run_id).status == "closed"
    assert run_of(http, run_id)["status"] == "closed"
    assert events_of(tenant, "finance.payroll.closed.v1")
    with pytest.raises(DBAPIError), as_role("worker"), tenant_session(tenant) as session:
        session.execute(
            text("UPDATE finance.payroll_run SET status = 'payment_pending' WHERE id = :i"),
            {"i": run_id},
        )


def test_a_run_that_is_not_fully_paid_cannot_be_closed(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {"destination": "ACC-HALF0002-PART"})
    release_and_settle(tenant, run_id)
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Exception, match="payment_pending|payment pending"):
            payments.request_close(
                session, tenant, make_user(tenant, ("finance",)).actor, UUID(str(run_id))
            )


def late_status(tenant, run_id, status, seq, reason=None):
    """A status the bank reports after the run was settled, applied the way the worker does."""
    with as_role("worker"), tenant_session(tenant) as session:
        line = session.scalars(
            select(PaymentLine).where(PaymentLine.run_id == UUID(str(run_id)))
        ).one()
        batch = session.get(PaymentBatch, line.batch_id)
        payments.apply_status(
            session,
            tenant,
            {
                "provider_ref": batch.provider_ref,
                "key": "k",
                "line_id": str(line.id),
                "status": status,
                "status_seq": seq,
                "amount_matches": True,
                "reason_code": reason,
            },
        )


def test_a_reversal_after_the_run_is_paid_reopens_it(tenant, slug):
    http, run_id, _ = paid_run(tenant, slug, {})
    late_status(tenant, run_id, "reversed", 2, "RETURNED_BY_BANK")
    assert statuses_of(tenant, run_id) == ["reversed"]
    assert run_row(tenant, run_id).status == "payment_pending"
    assert {p["status"] for p in http.get(f"{BASE}/payroll-runs/{run_id}/payslips").json()} == {
        "approved"
    }
    assert [i["code"] for i in payments_of(http, run_id)["open_issues"]] == ["PAYMENT_REVERSED"]


def test_a_paid_run_with_a_reversal_cannot_be_closed(tenant, slug):
    _, run_id, _ = paid_run(tenant, slug, {})
    late_status(tenant, run_id, "reversed", 2, "RETURNED_BY_BANK")
    with as_role("worker"), tenant_session(tenant) as session:
        with pytest.raises(Exception, match="payment pending"):
            payments.request_close(
                session, tenant, make_user(tenant, ("finance",)).actor, UUID(str(run_id))
            )


def test_closing_is_refused_at_approval_if_the_run_changed_since(tenant, slug):
    _, run_id, _ = paid_run(tenant, slug, {})
    proposal = propose_close(tenant, run_id)
    superuser_sql("UPDATE finance.payment_line SET status = 'reversed' WHERE run_id = :i", i=run_id)
    superuser_sql(
        "UPDATE finance.payroll_run SET status = 'payment_pending' WHERE id = :i", i=run_id
    )
    approve(tenant, make_user(tenant, ("finance",)), proposal.id)
    run_actions(tenant)
    assert proposal_status(tenant, proposal.id) == "failed"
    assert run_row(tenant, run_id).status == "payment_pending"


# ---------------------------------------------------------------------------- database guards


def test_a_payment_line_cannot_change_its_amount_or_key_or_be_deleted(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {})
    [line] = line_rows(tenant, run_id)
    for sql, match in [
        ("UPDATE finance.payment_line SET amount = 1 WHERE id = :i", "cannot be changed"),
        (
            "UPDATE finance.payment_line SET idempotency_key = 'x' WHERE id = :i",
            "cannot be changed",
        ),
        ("DELETE FROM finance.payment_line WHERE id = :i", "never deleted|permission denied"),
    ]:
        with (
            pytest.raises(DBAPIError, match=match),
            as_role("worker"),
            tenant_session(tenant) as session,
        ):
            session.execute(text(sql), {"i": line.id})


def test_a_payment_line_follows_the_status_path(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {})
    [line] = line_rows(tenant, run_id)
    with pytest.raises(DBAPIError, match="cannot go from due to paid"), as_role("worker"):
        with tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.payment_line SET status = 'paid' WHERE id = :i"),
                {"i": line.id},
            )


def test_the_api_role_cannot_write_payment_lines_or_batches(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {})
    [line] = line_rows(tenant, run_id)
    for sql in [
        "UPDATE finance.payment_line SET status = 'submitted' WHERE id = :i",
        "INSERT INTO finance.payment_batch (id) VALUES (gen_random_uuid())",
        "DELETE FROM finance.payment_status_event",
    ]:
        with pytest.raises(DBAPIError, match="permission denied"), as_role("api"):
            with tenant_session(tenant) as session:
                session.execute(text(sql), {"i": line.id})


def test_the_executor_cannot_read_finance_tables(tenant, slug):
    _, run_id, _ = approved_run(tenant, slug, {})
    for table in ("payment_line", "payment_batch", "payment_destination", "payroll_run"):
        with pytest.raises(DBAPIError, match="permission denied"), as_role("executor"):
            with tenant_session(tenant) as session:
                session.execute(text(f"SELECT * FROM finance.{table}"))


def test_a_batch_cannot_be_rewritten(tenant, slug):
    _, run_id, _ = paid_run(tenant, slug, {})
    with as_role("worker"), tenant_session(tenant) as session:
        batch = session.scalars(select(PaymentBatch)).one()
        batch_id = batch.id
    with pytest.raises(DBAPIError, match="cannot be changed"), as_role("worker"):
        with tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.payment_batch SET total = 1 WHERE id = :i"), {"i": batch_id}
            )


def test_destinations_are_isolated_between_tenants(tenant, other_tenant):
    paid_employee(tenant, destination="ACC-MINE0001")
    other = other_tenant
    with as_role("api"), tenant_session(other) as session:
        assert list(session.scalars(select(PaymentDestination))) == []


# ---------------------------------------------------------------------------- over HTTP (K9)

K9 = (
    "K9: the API role cannot insert proposals, so a person cannot propose over HTTP yet. "
    "See docs/FINANCE_PAYMENT_DESIGN.md. Remove this marker once the kernel allows it."
)


@pytest.mark.xfail(strict=True, reason=K9)
def test_a_release_can_be_proposed_over_http(tenant, slug):
    http, run_id, _ = approved_run(tenant, slug, {})
    assert http.post(f"{BASE}/payroll-runs/{run_id}/payments/release").status_code == 202


@pytest.mark.xfail(strict=True, reason=K9)
def test_a_close_can_be_proposed_over_http(tenant, slug):
    http, run_id, _ = paid_run(tenant, slug, {})
    assert http.post(f"{BASE}/payroll-runs/{run_id}/close").status_code == 202
