"""The golden rule: agents propose, humans approve, the executor acts."""

import pytest
from conftest import (
    as_role,
    declare_action,
    make_decision,
    make_proposal,
    make_user,
    superuser_sql,
)
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from kernel import trust
from kernel.db import tenant_session
from kernel.errors import (
    Conflict,
    MissingExplanation,
    PermissionDenied,
    StepUpRequired,
    UndeclaredAction,
    ValidationFailed,
)
from kernel.ids import uuid7
from kernel.trust import audit
from kernel.trust.models import Approval, AuditEvent, Proposal


class FakeAdapter:
    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[tuple] = []
        self.error = error

    def __call__(self, adapter, payload, key):
        self.calls.append((adapter, payload, key))
        if self.error:
            raise self.error
        return f"provider:{key}"


def approve(tenant, user, proposal_id, reason=None):
    with as_role("api"), tenant_session(tenant) as session:
        return trust.approve(session, user.actor, proposal_id, reason)


def execute(tenant, proposal_id, adapter):
    with as_role("executor"):
        return trust.execute(tenant, proposal_id, adapter)


def proposal_status(tenant, proposal_id):
    with as_role("api"), tenant_session(tenant) as session:
        return session.get(Proposal, proposal_id).status


def audit_results(tenant, action):
    with as_role("api"), tenant_session(tenant) as session:
        return session.scalars(select(AuditEvent.reason).where(AuditEvent.action == action)).all()


def test_happy_path_executes_and_audits(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    assert proposal.status == "pending_approval"

    approve(tenant, user, proposal.id, "Looks right")
    adapter = FakeAdapter()
    assert execute(tenant, proposal.id, adapter) == "succeeded"

    assert len(adapter.calls) == 1
    assert proposal_status(tenant, proposal.id) == "executed"
    with as_role("api"), tenant_session(tenant) as session:
        actions = session.scalars(select(AuditEvent.action).order_by(AuditEvent.seq)).all()
        assert audit.verify_chain(session).ok
    assert actions == [
        "proposal.created",
        "proposal.approved",
        "execution.started",
        "execution.succeeded",
    ]


def test_nothing_executes_without_approval(tenant):
    proposal = make_proposal(tenant)
    adapter = FakeAdapter()
    with as_role("worker"):
        assert trust.execute(tenant, proposal.id, adapter) == "skipped"
    assert adapter.calls == []
    assert proposal_status(tenant, proposal.id) == "pending_approval"


def test_editing_voids_the_approval(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id)

    with as_role("api"), tenant_session(tenant) as session:
        edited = trust.edit(session, user.actor, proposal.id, {"to": "b@example.test"}, "Fix")
        assert edited.status == "pending_approval"
        assert edited.revision == 2
        approvals = session.scalars(
            select(Approval).where(Approval.proposal_id == proposal.id)
        ).all()
        assert [a.status for a in approvals] == ["void"]

    adapter = FakeAdapter()
    assert execute(tenant, proposal.id, adapter) == "skipped"
    assert adapter.calls == []


def test_re_approval_after_edit_sends_the_edited_payload(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id)
    new_payload = {"to": "b@example.test", "subject": "Edited", "body": "Edited"}
    with as_role("api"), tenant_session(tenant) as session:
        trust.edit(session, user.actor, proposal.id, new_payload)
    approve(tenant, user, proposal.id)

    adapter = FakeAdapter()
    assert execute(tenant, proposal.id, adapter) == "succeeded"
    assert adapter.calls[0][1] == new_payload


def test_payload_tampered_after_approval_is_blocked(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id)
    superuser_sql(
        """UPDATE trust.proposal SET payload = '{"to": "evil@example.test"}' WHERE id = :id""",
        id=proposal.id,
    )

    adapter = FakeAdapter()
    assert execute(tenant, proposal.id, adapter) == "skipped"
    assert adapter.calls == []
    assert proposal_status(tenant, proposal.id) == "blocked"
    assert "payload_tampered" in audit_results(tenant, "execution.denied")


def test_duplicate_execution_calls_the_provider_once(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id)
    adapter = FakeAdapter()
    assert execute(tenant, proposal.id, adapter) == "succeeded"
    assert execute(tenant, proposal.id, adapter) == "skipped"
    assert len(adapter.calls) == 1


def test_crash_after_send_produces_no_duplicate(tenant):
    """The process dies after the provider accepted, before anything is recorded."""
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id)

    crashing = FakeAdapter(error=SystemExit("killed"))
    with pytest.raises(SystemExit):
        execute(tenant, proposal.id, crashing)
    assert proposal_status(tenant, proposal.id) == "executing"

    restarted = FakeAdapter()
    assert execute(tenant, proposal.id, restarted) == "skipped"
    assert restarted.calls == []

    from datetime import timedelta

    with as_role("executor"):
        settled = trust.reconcile_stale(
            tenant, lambda adapter, key: f"found:{key}", older_than=timedelta(0)
        )
    assert settled == 1
    assert proposal_status(tenant, proposal.id) == "executed"
    assert restarted.calls == []


def test_crash_with_no_trace_goes_to_a_person_not_a_retry(tenant):
    from datetime import timedelta

    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id)
    with pytest.raises(SystemExit):
        execute(tenant, proposal.id, FakeAdapter(error=SystemExit("killed")))
    with as_role("executor"):
        trust.reconcile_stale(tenant, lambda adapter, key: None, older_than=timedelta(0))
    assert proposal_status(tenant, proposal.id) == "unknown"


def test_provider_timeout_is_unknown_and_never_retried(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id)
    assert execute(tenant, proposal.id, FakeAdapter(error=TimeoutError())) == "unknown"
    retry = FakeAdapter()
    assert execute(tenant, proposal.id, retry) == "skipped"
    assert retry.calls == []


def test_definite_rejection_is_failed(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id)
    adapter = FakeAdapter(error=trust.AdapterRejected("Domain not allowed"))
    assert execute(tenant, proposal.id, adapter) == "failed"


def test_unauthorized_approver_is_denied_and_audited(tenant):
    proposal = make_proposal(tenant)
    outsider = make_user(tenant, roles=("employee",))
    with pytest.raises(PermissionDenied):
        approve(tenant, outsider, proposal.id)
    assert proposal_status(tenant, proposal.id) == "pending_approval"
    assert "two_key_failed" in audit_results(tenant, "proposal.approve")


def test_two_keys_seeing_is_not_approving(tenant):
    auditor = make_user(tenant, roles=("auditor",))
    proposal = make_proposal(tenant)
    with pytest.raises(PermissionDenied):
        approve(tenant, auditor, proposal.id)


def test_scoped_role_only_works_inside_its_scope(tenant):
    action = declare_action("test.scoped", approver_roles=("manager",), view_roles=("manager",))
    manager = make_user(tenant, roles=("manager",), scope=("org_unit", "ORG-ENG"))
    other_team = make_proposal(tenant, action, target={"org_unit": "ORG-SAL"})
    own_team = make_proposal(tenant, action, target={"org_unit": "ORG-ENG"})
    with pytest.raises(PermissionDenied):
        approve(tenant, manager, other_team.id)
    approve(tenant, manager, own_team.id)
    assert proposal_status(tenant, own_team.id) == "approved"


def test_r3_requires_step_up(tenant):
    action = declare_action("test.r3", risk="R3")
    proposal = make_proposal(tenant, action)
    with pytest.raises(StepUpRequired):
        approve(tenant, make_user(tenant, step_up=False), proposal.id)
    approve(tenant, make_user(tenant, step_up=True), proposal.id)
    assert execute(tenant, proposal.id, FakeAdapter()) == "succeeded"


def test_r3_forbids_self_approval(tenant):
    action = declare_action("test.r3", risk="R3")
    requester = make_user(tenant, step_up=True)
    proposal = make_proposal(tenant, action, requested_by=requester.id)
    with pytest.raises(PermissionDenied):
        approve(tenant, requester, proposal.id)
    assert "self_approval" in audit_results(tenant, "proposal.approve")


def test_r3_editor_cannot_approve_their_own_edit(tenant):
    action = declare_action("test.r3", risk="R3")
    editor = make_user(tenant, step_up=True)
    proposal = make_proposal(tenant, action)
    with as_role("api"), tenant_session(tenant) as session:
        trust.edit(session, editor.actor, proposal.id, {"to": "x@example.test"})
    with pytest.raises(PermissionDenied):
        approve(tenant, editor, proposal.id)


def test_approver_who_lost_access_blocks_execution(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id)
    superuser_sql("DELETE FROM core.role_assignment WHERE user_id = :id", id=user.id)
    adapter = FakeAdapter()
    assert execute(tenant, proposal.id, adapter) == "skipped"
    assert adapter.calls == []
    assert "approver_not_authorized" in audit_results(tenant, "execution.denied")


def test_expired_approval_blocks_execution(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id)
    superuser_sql(
        "UPDATE trust.approval SET expires_at = now() - interval '1 minute' "
        "WHERE proposal_id = :id",
        id=proposal.id,
    )
    assert execute(tenant, proposal.id, FakeAdapter()) == "skipped"
    assert "approval_expired" in audit_results(tenant, "execution.denied")


def test_expired_proposal_cannot_be_approved(tenant):
    proposal = make_proposal(tenant)
    superuser_sql(
        "UPDATE trust.proposal SET expires_at = now() - interval '1 minute' WHERE id = :id",
        id=proposal.id,
    )
    with pytest.raises(Conflict):
        approve(tenant, make_user(tenant), proposal.id)


def test_rejection_requires_a_reason_and_stops_execution(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    with as_role("api"), tenant_session(tenant) as session, pytest.raises(ValidationFailed):
        trust.reject(session, user.actor, proposal.id, "  ")
    with as_role("api"), tenant_session(tenant) as session:
        trust.reject(session, user.actor, proposal.id, "Wrong tone")
    assert proposal_status(tenant, proposal.id) == "rejected"
    assert execute(tenant, proposal.id, FakeAdapter()) == "skipped"


def test_no_explanation_no_proposal(tenant):
    action = declare_action("test.email.r2")
    with as_role("worker"), tenant_session(tenant) as session, pytest.raises(MissingExplanation):
        trust.propose(session, tenant, action, {"a": 1}, "No why", None, "key:1")
    assert "missing_explanation" in audit_results(tenant, action)


def test_undeclared_action_is_refused(tenant):
    with as_role("worker"), tenant_session(tenant) as session, pytest.raises(UndeclaredAction):
        trust.propose(session, tenant, "test.nope", {"a": 1}, "?", uuid7(), "key:2")


def test_r0_action_cannot_become_a_proposal(tenant):
    action = declare_action("test.r0", risk="R0", channel="none")
    with as_role("worker"), tenant_session(tenant) as session, pytest.raises(ValidationFailed):
        trust.propose(session, tenant, action, {"a": 1}, "?", uuid7(), "key:3")


def test_same_idempotency_key_returns_the_same_proposal(tenant):
    action = declare_action("test.email.r2")
    decision_id = make_decision(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        first = trust.propose(session, tenant, action, {"a": 1}, "x", decision_id, "key:same")
        second = trust.propose(session, tenant, action, {"a": 2}, "y", decision_id, "key:same")
    assert first.id == second.id


def test_old_policy_approval_is_blocked(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id)
    superuser_sql(
        "UPDATE trust.approval SET policy_version = 'older-policy' WHERE proposal_id = :id",
        id=proposal.id,
    )
    assert execute(tenant, proposal.id, FakeAdapter()) == "skipped"
    assert "policy_changed" in audit_results(tenant, "execution.denied")


# ----- Audit chain -----


def test_tampered_audit_row_fails_verification(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id, "Original reason")
    with as_role("api"), tenant_session(tenant) as session:
        assert audit.verify_chain(session).ok

    superuser_sql(
        "UPDATE trust.audit_event SET reason = 'Forged' "
        "WHERE tenant_id = :t AND action = 'proposal.approved'",
        t=tenant,
    )
    with as_role("api"), tenant_session(tenant) as session:
        status = audit.verify_chain(session)
    assert not status.ok
    assert status.first_bad_seq == 2


def test_deleted_audit_row_fails_verification(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    approve(tenant, user, proposal.id)
    superuser_sql("DELETE FROM trust.audit_event WHERE tenant_id = :t AND seq = 1", t=tenant)
    with as_role("api"), tenant_session(tenant) as session:
        assert not audit.verify_chain(session).ok


@pytest.mark.parametrize("role", ["api", "worker", "executor", "owner"])
def test_no_role_can_change_audit_history(tenant, role):
    proposal = make_proposal(tenant)
    assert proposal
    with as_role(role), pytest.raises(DBAPIError), tenant_session(tenant) as session:
        session.execute(text("UPDATE trust.audit_event SET reason = 'x'"))
    with as_role(role), pytest.raises(DBAPIError), tenant_session(tenant) as session:
        session.execute(text("DELETE FROM trust.audit_event"))


def test_audit_write_failure_fails_the_action(tenant, monkeypatch):
    user = make_user(tenant)
    proposal = make_proposal(tenant)

    def broken(*args, **kwargs):
        raise RuntimeError("Audit sink down")

    monkeypatch.setattr(trust.audit, "append", broken)
    with pytest.raises(RuntimeError):
        approve(tenant, user, proposal.id)
    monkeypatch.undo()
    assert proposal_status(tenant, proposal.id) == "pending_approval"
    with as_role("api"), tenant_session(tenant) as session:
        assert (
            session.scalars(select(Approval).where(Approval.proposal_id == proposal.id)).all() == []
        )


# ----- Database-level rules: these hold even if application code has a bug -----


def test_worker_role_cannot_approve(tenant):
    proposal = make_proposal(tenant)
    with as_role("worker"), pytest.raises(ProgrammingError), tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO trust.approval (id, tenant_id, proposal_id, payload_hash, decision, "
                "status, approver_id, approver_roles, step_up, policy_version, expires_at, "
                "created_at) VALUES (gen_random_uuid(), :t, :p, :h, 'approved', 'active', "
                "gen_random_uuid(), '{}', false, 'x', now(), now())"
            ),
            {"t": tenant, "p": proposal.id, "h": proposal.payload_hash},
        )


def test_executor_role_cannot_approve(tenant):
    proposal = make_proposal(tenant)
    with as_role("executor"), pytest.raises(ProgrammingError), tenant_session(tenant) as session:
        session.execute(
            text("UPDATE trust.approval SET decision = 'approved' WHERE proposal_id = :p"),
            {"p": proposal.id},
        )


def test_api_role_cannot_record_an_execution(tenant):
    proposal = make_proposal(tenant)
    with as_role("api"), pytest.raises(ProgrammingError), tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO trust.execution (id, tenant_id, proposal_id, approval_id, "
                "idempotency_key, status, created_at) VALUES (gen_random_uuid(), :t, :p, "
                "gen_random_uuid(), 'x', 'succeeded', now())"
            ),
            {"t": tenant, "p": proposal.id},
        )


def test_database_rejects_approval_with_wrong_hash(tenant):
    user = make_user(tenant)
    proposal = make_proposal(tenant)
    with as_role("api"), pytest.raises(DBAPIError), tenant_session(tenant) as session:
        session.add(
            Approval(
                tenant_id=tenant,
                proposal_id=proposal.id,
                payload_hash="f" * 64,
                decision="approved",
                approver_id=user.id,
                approver_roles=["hr"],
                policy_version="x",
                expires_at=proposal.expires_at,
            )
        )
        session.flush()


def test_executor_cannot_see_drafts_only_approved_work(tenant):
    user = make_user(tenant)
    draft = make_proposal(tenant)
    approved = make_proposal(tenant)
    approve(tenant, user, approved.id)
    with as_role("executor"), tenant_session(tenant) as session:
        visible = session.scalars(select(Proposal.id)).all()
    assert approved.id in visible
    assert draft.id not in visible


def test_executor_cannot_read_decisions_or_pack_data(tenant):
    make_proposal(tenant)
    for sql in (
        "SELECT * FROM trust.decision_record",
        "SELECT * FROM trust.decision_evidence",
        "SELECT * FROM core.employee",
        "SELECT * FROM ai.agent_run",
    ):
        with (
            as_role("executor"),
            pytest.raises(ProgrammingError),
            tenant_session(tenant) as session,
        ):
            session.execute(text(sql))


def test_role_escalation_tables_are_read_only_for_agents(tenant):
    with as_role("executor"), pytest.raises(ProgrammingError), tenant_session(tenant) as session:
        session.execute(text("DELETE FROM core.role_assignment"))
    with as_role("api"), pytest.raises(ProgrammingError), tenant_session(tenant) as session:
        session.execute(text("UPDATE trust.action_type SET risk = 'R0'"))
    with as_role("worker"), pytest.raises(ProgrammingError), tenant_session(tenant) as session:
        session.execute(text("UPDATE trust.action_type SET risk = 'R0'"))


# ----- Tenant isolation -----


def test_rls_blocks_cross_tenant_reads(tenant, other_tenant):
    proposal = make_proposal(tenant)
    with as_role("api"), tenant_session(other_tenant) as session:
        assert session.get(Proposal, proposal.id) is None
        assert session.scalars(select(AuditEvent)).all() == []


def test_rls_blocks_cross_tenant_writes(tenant, other_tenant):
    proposal = make_proposal(tenant)
    with as_role("api"), tenant_session(other_tenant) as session:
        result = session.execute(
            text("UPDATE trust.proposal SET summary = 'hacked' WHERE id = :id"), {"id": proposal.id}
        )
        assert result.rowcount == 0
    with (
        as_role("worker"),
        pytest.raises(ProgrammingError),
        tenant_session(other_tenant) as session,
    ):
        session.execute(
            text(
                "INSERT INTO core.person (id, tenant_id, external_id, lifecycle, created_at) "
                "VALUES (gen_random_uuid(), :t, 'x', 'candidate', now())"
            ),
            {"t": tenant},
        )


def test_no_tenant_set_means_no_rows(tenant):
    make_proposal(tenant)
    from kernel.db import global_session

    with as_role("api"), global_session() as session:
        assert session.scalars(select(Proposal)).all() == []
        assert session.scalars(select(AuditEvent)).all() == []
