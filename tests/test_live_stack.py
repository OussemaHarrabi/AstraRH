"""End to end against the running processes: real worker, real executor, real mailbox.
Runs through `python astra.py smoke`, because it needs the whole stack up."""

import os
import time
from uuid import uuid4

import httpx
import pytest
from conftest import _delete_tenant, as_role, make_proposal, make_tenant, make_user
from sqlalchemy import select, text

from kernel import graph, registry, trust
from kernel.adapters import mail
from kernel.db import global_session, tenant_session
from kernel.trust.models import AuditEvent, Proposal

live_only = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_STACK") != "1", reason="Needs the full stack: python astra.py smoke"
)
WAIT_SECONDS = 45

registry.install_graph_projections()


def wait_for(condition, what: str):
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        result = condition()
        if result:
            return result
        time.sleep(0.5)
    raise AssertionError(f"Timed out waiting for {what}")


@live_only
def test_approved_email_is_sent_by_the_real_executor():
    tenant = make_tenant()
    with as_role("owner"), global_session() as session:
        session.execute(text("UPDATE core.tenant SET active = true WHERE id = :t"), {"t": tenant})
    try:
        subject = f"Live test {uuid4().hex}"
        approver = make_user(tenant, roles=("hr",))
        proposal = make_proposal(
            tenant,
            "kernel.email.send",
            payload={"to": "candidate@mail.example.test", "subject": subject, "body": "Hello"},
        )
        search = {"query": f'subject:"{subject}"'}
        url = f"http://{os.environ['SMTP_HOST']}:8025/api/v1/search"

        time.sleep(2)
        assert httpx.get(url, params=search).json()["messages_count"] == 0, "Sent without approval"

        with as_role("api"), tenant_session(tenant) as session:
            trust.approve(session, approver.actor, proposal.id, "Reviewed")

        def executed():
            with as_role("api"), tenant_session(tenant) as session:
                return session.get(Proposal, proposal.id).status == "executed"

        wait_for(executed, "the executor to run the proposal")
        assert httpx.get(url, params=search).json()["messages_count"] == 1

        with as_role("api"), tenant_session(tenant) as session:
            actions = session.scalars(select(AuditEvent.action).order_by(AuditEvent.seq)).all()
            assert trust.audit.verify_chain(session).ok
        assert actions[-1] == "execution.succeeded"

        def projected():
            result = graph.query(tenant, "agent_mesh")
            return {"APPROVED_BY", "EXECUTED", "EMITTED"} <= {e["type"] for e in result["edges"]}

        wait_for(projected, "the worker to project the events into Neo4j")
    finally:
        with as_role("owner"), global_session() as session:
            session.execute(
                text("UPDATE core.tenant SET active = false WHERE id = :t"), {"t": tenant}
            )
        time.sleep(2)
        with graph._get_driver().session() as neo:
            neo.run("MATCH (n {tenant_id: $t}) DETACH DELETE n", t=str(tenant))
        _delete_tenant(tenant)


def test_mail_adapter_refuses_outside_domains():
    with pytest.raises(trust.AdapterRejected):
        mail.send({"to": "someone@gmail.com", "subject": "x", "body": "y"}, "key")


def test_mail_adapter_requires_content():
    with pytest.raises(trust.AdapterRejected):
        mail.send({"to": "a@example.test", "subject": "", "body": ""}, "key")


def test_mail_adapter_sends_and_can_be_reconciled():
    key = f"test:{uuid4().hex}"
    assert mail.find(key) is None
    reference = mail.send({"to": "a@example.test", "subject": "Hi", "body": "Hello"}, key)
    assert mail.find(key) == reference
