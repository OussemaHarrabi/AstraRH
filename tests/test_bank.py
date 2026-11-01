"""The sandbox bank: a deterministic stand-in whose behaviour the account token decides."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.bank import main as bank


@pytest.fixture(autouse=True)
def clean_bank():
    bank._batches.clear()
    bank._statuses.clear()


client = TestClient(bank.app)


def line(account="ACC-GOOD0001", amount="100.000"):
    return {"line_id": str(uuid4()), "token": account, "amount": amount}


def batch(*lines, key=None, total=None):
    lines = lines or (line(),)
    from decimal import Decimal

    return {
        "key": key or f"release:{uuid4()}",
        "tenant_id": str(uuid4()),
        "lines": list(lines),
        "total": total or format(sum(Decimal(item["amount"]) for item in lines), "f"),
    }


def post(body):
    return client.post("/batches", json=body)


def statuses(since=0):
    return client.get("/statuses", params={"since": since}).json()


def test_the_bank_is_healthy():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_a_batch_is_accepted_and_every_line_is_paid():
    body = batch(line(), line("ACC-GOOD0002", "50.500"))
    response = post(body)
    assert response.status_code == 201
    reference = response.json()["reference"]
    assert reference.startswith("BANK-")
    result = statuses()
    assert [s["status"] for s in result["statuses"]] == ["paid", "paid"]
    assert {s["reference"] for s in result["statuses"]} == {reference}
    assert [s["paid_amount"] for s in result["statuses"]] == ["100.000", "50.500"]
    assert result["cursor"] == 2


def test_the_same_batch_twice_pays_once():
    body = batch(line(), line("ACC-GOOD0002", "20.000"))
    first, second = post(body), post(body)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json() == second.json()
    assert len(statuses()["statuses"]) == 2


def test_a_key_cannot_be_reused_for_a_different_batch():
    key = f"release:{uuid4()}"
    assert post(batch(line(), key=key)).status_code == 201
    other = post(batch(line(amount="999.000"), key=key))
    assert other.status_code == 409
    assert "different batch" in other.json()["detail"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (batch(line("not-a-token")), "does not accept"),
        (batch(line("ACC-x")), "does not accept"),
        (batch(line(amount="10")), "does not accept"),
        (batch(line(amount="-5.000")), "does not accept"),
        (batch(line("ACC-BAD0001-REFUSE")), "refused"),
        (batch(line(), total="1.000"), "total does not match"),
    ],
)
def test_a_batch_the_bank_does_not_accept_is_refused_and_nothing_is_recorded(body, message):
    response = post(body)
    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert statuses()["statuses"] == []
    assert client.get(f"/batches/{body['key']}").status_code == 404


def test_a_refused_line_refuses_the_whole_batch():
    response = post(batch(line(), line("ACC-BAD00001-REFUSE")))
    assert response.status_code == 422
    assert statuses()["statuses"] == []


def test_a_batch_can_be_found_by_its_key_and_an_unknown_one_cannot():
    body = batch()
    reference = post(body).json()["reference"]
    assert client.get(f"/batches/{body['key']}").json() == {"reference": reference}
    assert client.get("/batches/release:nobody").status_code == 404


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("ACC-AAAA0001-FAIL", [("failed", "0.000", "ACCOUNT_CLOSED")]),
        ("ACC-AAAA0002-PART", [("part_paid", "50.000", None)]),
        (
            "ACC-AAAA0003-REV",
            [("paid", "100.000", None), ("reversed", "100.000", "RETURNED_BY_BANK")],
        ),
        ("ACC-AAAA0004-MISMATCH", [("paid", "99.000", None)]),
        ("ACC-AAAA0005", [("paid", "100.000", None)]),
    ],
)
def test_the_token_decides_what_the_bank_does(token, expected):
    post(batch(line(token)))
    got = [(s["status"], s["paid_amount"], s["reason"]) for s in statuses()["statuses"]]
    assert got == expected
    assert [s["seq"] for s in statuses()["statuses"]] == list(range(1, len(expected) + 1))


def test_statuses_are_read_from_a_cursor():
    post(batch(line(), line("ACC-GOOD0002", "5.000")))
    first = statuses()
    assert first["cursor"] == 2
    post(batch(line("ACC-GOOD0003", "7.000")))
    later = statuses(since=first["cursor"])
    assert [s["paid_amount"] for s in later["statuses"]] == ["7.000"]
    assert later["cursor"] == 3
    assert statuses(since=3) == {"cursor": 3, "statuses": []}


def test_an_empty_bank_reports_the_cursor_it_was_given():
    assert statuses(since=7) == {"cursor": 7, "statuses": []}
