"""The bank adapter: validation without a network, then sending, finding and polling against the
sandbox bank running in-process."""

from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.bank import main as bank
from kernel import adapters
from kernel.adapters import payments
from kernel.payments import MAX_LINES
from kernel.trust import AdapterRejected


@pytest.fixture(autouse=True)
def in_process_bank(monkeypatch):
    bank._batches.clear()
    bank._statuses.clear()
    client = TestClient(bank.app)
    monkeypatch.setattr(
        payments, "_request", lambda method, path, **kw: client.request(method, path, **kw)
    )


def release(*pairs, **changes):
    lines = [
        {"line_id": str(uuid4()), "token": token, "amount": amount, "key": f"pay:{uuid4()}"}
        for token, amount in (pairs or (("ACC-GOOD0001", "100.000"),))
    ]
    payload = {
        "run_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "release_number": 1,
        "currency": "TND",
        "lines": lines,
        "total": format(sum(Decimal(item["amount"]) for item in lines), "f"),
        "count": len(lines),
    }
    payload.update(changes)
    return payload


def test_a_valid_release_is_shaped_for_the_bank():
    payload = release(("ACC-GOOD0001", "100.000"), ("ACC-GOOD0002", "50.500"))
    body = payments.build(payload, "release:1")
    assert body["key"] == "release:1"
    assert body["tenant_id"] == payload["tenant_id"]
    assert body["total"] == "150.500"
    assert [(i["token"], i["amount"]) for i in body["lines"]] == [
        ("ACC-GOOD0001", "100.000"),
        ("ACC-GOOD0002", "50.500"),
    ]
    assert set(body["lines"][0]) == {"line_id", "token", "amount"}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"lines": []}, "at least one line"),
        ({"lines": "none"}, "at least one line"),
        ({"currency": "EUR"}, "TND"),
        ({"currency": None}, "TND"),
        ({"total": "1.000"}, "total does not match"),
        ({"count": 5}, "count does not match"),
    ],
)
def test_a_malformed_release_is_refused_before_any_network_call(changes, message):
    with pytest.raises(AdapterRejected, match=message):
        payments.build(release(**changes), "release:1")


@pytest.mark.parametrize(
    ("token", "amount", "message"),
    [
        ("12345678", "100.000", "token that is not allowed"),
        ("acc-lower0001", "100.000", "token that is not allowed"),
        ("ACC-x", "100.000", "token that is not allowed"),
        ("ACC-GOOD0001 ", "100.000", "token that is not allowed"),
        ("ACC-GOOD0001", "0.000", "above zero"),
        ("ACC-GOOD0001", "-1.000", "above zero"),
        ("ACC-GOOD0001", "100", "above zero"),
        ("ACC-GOOD0001", "1e3", "above zero"),
        ("ACC-GOOD0001", "100.0000", "above zero"),
    ],
)
def test_a_bad_token_or_amount_is_refused(token, amount, message):
    payload = release(("ACC-GOOD0001", "100.000"))
    payload["lines"][0].update(token=token, amount=amount)
    payload["total"] = "100.000"
    with pytest.raises(AdapterRejected, match=message):
        payments.build(payload, "release:1")


def test_a_line_that_is_incomplete_or_repeated_is_refused():
    payload = release(("ACC-GOOD0001", "100.000"))
    del payload["lines"][0]["token"]
    with pytest.raises(AdapterRejected, match="incomplete"):
        payments.build(payload, "release:1")
    payload = release(("ACC-GOOD0001", "100.000"), ("ACC-GOOD0002", "100.000"))
    payload["lines"][1]["line_id"] = payload["lines"][0]["line_id"]
    with pytest.raises(AdapterRejected, match="appears twice"):
        payments.build(payload, "release:1")
    payload = release(("ACC-GOOD0001", "100.000"))
    payload["lines"][0]["line_id"] = "not-a-uuid"
    with pytest.raises(AdapterRejected, match="incomplete"):
        payments.build(payload, "release:1")


def test_too_many_lines_are_refused():
    pairs = [("ACC-GOOD0001", "1.000")] * (MAX_LINES + 1)
    payload = release(*pairs)
    with pytest.raises(AdapterRejected, match="at most"):
        payments.build(payload, "release:1")


def test_sending_returns_the_banks_reference_and_the_bank_pays_each_line():
    payload = release(("ACC-GOOD0001", "100.000"), ("ACC-GOOD0002", "50.000"))
    reference = payments.send(payload, "release:send")
    assert reference.startswith("BANK-")
    cursor, found = payments.statuses(0)
    assert cursor == 2
    assert [(s["status"], s["paid_amount"]) for s in found] == [
        ("paid", "100.000"),
        ("paid", "50.000"),
    ]


def test_sending_the_same_batch_twice_pays_once():
    payload = release(("ACC-GOOD0001", "100.000"))
    first = payments.send(payload, "release:twice")
    second = payments.send(payload, "release:twice")
    assert first == second
    assert len(payments.statuses(0)[1]) == 1


def test_a_batch_the_bank_refuses_is_a_definite_refusal():
    payload = release(("ACC-BAD00001-REFUSE", "100.000"))
    with pytest.raises(AdapterRejected, match="refused"):
        payments.send(payload, "release:refused")
    assert payments.find("release:refused") is None
    assert payments.statuses(0)[1] == []


def test_a_server_error_leaves_the_outcome_unknown_not_refused(monkeypatch):
    def broken(method, path, **kwargs):
        return httpx.Response(500, request=httpx.Request(method, f"http://bank{path}"))

    monkeypatch.setattr(payments, "_request", broken)
    with pytest.raises(httpx.HTTPStatusError):
        payments.send(release(), "release:broken")


def test_a_timeout_propagates_so_the_executor_records_unknown(monkeypatch):
    def slow(method, path, **kwargs):
        raise httpx.ReadTimeout("no answer")

    monkeypatch.setattr(payments, "_request", slow)
    with pytest.raises(httpx.ReadTimeout):
        payments.send(release(), "release:slow")


def test_a_batch_can_be_found_by_its_key_even_with_odd_characters():
    key = f"finance.payment.release:{uuid4()}:1/special"
    reference = payments.send(release(), key)
    assert payments.find(key) == reference
    assert payments.find("finance.payment.release:never:1") is None


def test_the_executor_entry_points_use_this_adapter():
    payload = release()
    reference = adapters.run("payment.release", payload, "release:via-run")
    assert adapters.lookup("payment.release", "release:via-run") == reference
    cursor, found = adapters.poll(0)
    assert (cursor, len(found)) == (1, 1)
    with pytest.raises(AdapterRejected, match="Unknown adapter"):
        adapters.run("payment.unknown", payload, "k")
