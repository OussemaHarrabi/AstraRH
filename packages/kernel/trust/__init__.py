"""The trust ledger: agents propose, humans approve, the executor acts.

    propose()  by an agent or a person, for R2 and R3 actions. Needs a DecisionRecord.
    edit()     by a person. Voids any approval.
    approve()  by a person, bound to the payload hash.
    execute()  re-validates everything, claims the idempotency key, then acts.

R0 and R1 actions don't need approval: log them with log_action().
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

from opentelemetry import trace
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kernel.authz import can_approve, has_role
from kernel.canonical import payload_hash
from kernel.db import tenant_session, utcnow
from kernel.errors import (
    Conflict,
    MissingExplanation,
    NotFound,
    PermissionDenied,
    StepUpRequired,
    UndeclaredAction,
    ValidationFailed,
)
from kernel.events import event_type, publish
from kernel.identity import Actor
from kernel.identity.models import RoleAssignment
from kernel.trust import audit
from kernel.trust.models import ActionType, Approval, AuditEvent, Execution, PolicyVersion, Proposal

__all__ = [
    "ActionType",
    "AdapterRejected",
    "Approval",
    "AuditEvent",
    "Execution",
    "PolicyVersion",
    "Proposal",
    "approve",
    "audit",
    "edit",
    "execute",
    "log_action",
    "propose",
    "reconcile_stale",
    "reject",
    "supersede",
]

PROPOSAL_TTL = timedelta(days=7)
APPROVAL_TTL = timedelta(hours=24)
APPROVAL_REQUIRED = {"R2", "R3"}
AUTOMATIC = {"R0", "R1"}
STALE_EXECUTION = timedelta(minutes=2)

tracer = trace.get_tracer("astra.trust")


class AdapterRejected(Exception):  # noqa: N818 - a definite outcome, not a generic error
    """The destination definitely refused. Unlike a timeout, nothing can have been done."""


@event_type("trust.proposal.created.v1")
class ProposalCreated(BaseModel):
    proposal_id: UUID
    action_type: str
    pack: str
    risk: str
    agent_run_id: UUID | None = None
    decision_record_id: UUID


@event_type("trust.proposal.approved.v1")
class ProposalApproved(BaseModel):
    proposal_id: UUID
    approver_id: UUID
    action_type: str


@event_type("trust.proposal.rejected.v1")
class ProposalRejected(BaseModel):
    proposal_id: UUID
    approver_id: UUID
    action_type: str


@event_type("trust.action.executed.v1")
class ActionExecuted(BaseModel):
    proposal_id: UUID
    action_type: str
    pack: str
    execution_id: UUID
    target: dict[str, Any]


def _action_type(session: Session, action_id: str) -> ActionType:
    action = session.get(ActionType, action_id)
    if action is None:
        raise UndeclaredAction(f"Action {action_id} is not declared in any manifest")
    return action


def current_policy_version(session: Session) -> str:
    version = session.scalar(select(PolicyVersion.version).where(PolicyVersion.is_current))
    if version is None:
        raise ValidationFailed("No current policy version: run migrations")
    return version


def log_action(
    session: Session,
    tenant_id: UUID,
    action_id: str,
    actor_type: str,
    actor_id: str,
    **details: Any,
) -> AuditEvent:
    """Record an automatic R0/R1 action. Declared actions only."""
    action = _action_type(session, action_id)
    if action.risk not in AUTOMATIC:
        raise ValidationFailed(f"{action_id} is {action.risk}: it needs a proposal and approval")
    return audit.append(session, tenant_id, actor_type, actor_id, action_id, **details)


def propose(
    session: Session,
    tenant_id: UUID,
    action_id: str,
    payload: dict[str, Any],
    summary: str,
    decision_record_id: UUID | None,
    idempotency_key: str,
    target: dict[str, Any] | None = None,
    agent_run_id: UUID | None = None,
    requested_by: UUID | None = None,
    expires_in: timedelta = PROPOSAL_TTL,
) -> Proposal:
    actor_id = str(agent_run_id or requested_by or "system")
    actor_type = "agent" if agent_run_id else "human" if requested_by else "system"
    action = session.get(ActionType, action_id)
    if action is None:
        audit.record_denial(tenant_id, actor_type, actor_id, action_id, "undeclared_action")
        raise UndeclaredAction(f"Action {action_id} is not declared in any manifest")
    if action.risk not in APPROVAL_REQUIRED:
        raise ValidationFailed(f"{action_id} is {action.risk}: use log_action, not a proposal")
    if decision_record_id is None:
        audit.record_denial(tenant_id, actor_type, actor_id, action_id, "missing_explanation")
        raise MissingExplanation(f"{action_id} needs a DecisionRecord: no explanation, no proposal")

    existing = session.scalar(select(Proposal).where(Proposal.idempotency_key == idempotency_key))
    if existing is not None:
        return existing

    policy = current_policy_version(session)
    proposal = Proposal(
        tenant_id=tenant_id,
        action_type=action_id,
        status="pending_approval",
        risk=action.risk,
        channel=action.channel,
        summary=summary,
        payload=payload,
        payload_hash=payload_hash(payload),
        target=target or {},
        decision_record_id=decision_record_id,
        idempotency_key=idempotency_key,
        policy_version=policy,
        agent_run_id=agent_run_id,
        requested_by=requested_by,
        expires_at=utcnow() + expires_in,
    )
    session.add(proposal)
    session.flush()
    audit.append(
        session,
        tenant_id,
        actor_type,
        actor_id,
        "proposal.created",
        proposal_id=proposal.id,
        policy_version=policy,
        output_hash=proposal.payload_hash,
        data={"action_type": action_id, "risk": action.risk},
    )
    publish(
        session,
        tenant_id,
        ProposalCreated(
            proposal_id=proposal.id,
            action_type=action_id,
            pack=action.pack,
            risk=action.risk,
            agent_run_id=agent_run_id,
            decision_record_id=decision_record_id,
        ),
    )
    return proposal


def supersede(session: Session, proposal: Proposal, actor_id: str, reason: str) -> None:
    """Newer work replaced this suggestion, so nobody should approve the stale one."""
    proposal.status = "superseded"
    audit.append(
        session,
        proposal.tenant_id,
        "agent",
        actor_id,
        "proposal.superseded",
        proposal_id=proposal.id,
        reason=reason,
    )


def _locked_proposal(session: Session, proposal_id: UUID) -> Proposal:
    proposal = session.get(Proposal, proposal_id, with_for_update=True)
    if proposal is None:
        raise NotFound("Proposal not found")
    return proposal


def _void_active_approvals(session: Session, proposal_id: UUID) -> None:
    rows = session.scalars(
        select(Approval).where(Approval.proposal_id == proposal_id, Approval.status == "active")
    )
    for approval in rows:
        approval.status = "void"


def edit(
    session: Session,
    actor: Actor,
    proposal_id: UUID,
    new_payload: dict[str, Any],
    reason: str | None = None,
) -> Proposal:
    proposal = _locked_proposal(session, proposal_id)
    action = _action_type(session, proposal.action_type)
    if not has_role(actor, action.view_roles, proposal.target):
        audit.record_denial(
            actor.tenant_id,
            "human",
            actor.user_id,
            "proposal.edit",
            "no_view_access",
            proposal_id=proposal_id,
        )
        raise PermissionDenied("You cannot edit this proposal.")
    if proposal.status not in {"pending_approval", "approved", "blocked"}:
        raise Conflict(f"A proposal in status {proposal.status} cannot be edited")

    _void_active_approvals(session, proposal_id)
    previous_hash = proposal.payload_hash
    proposal.payload = new_payload
    proposal.payload_hash = payload_hash(new_payload)
    proposal.revision += 1
    proposal.last_edited_by = actor.user_id
    proposal.status = "pending_approval"
    audit.append(
        session,
        actor.tenant_id,
        "human",
        actor.user_id,
        "proposal.edited",
        proposal_id=proposal.id,
        input_hash=previous_hash,
        output_hash=proposal.payload_hash,
        reason=reason,
        data={"revision": proposal.revision},
    )
    return proposal


def approve(
    session: Session, actor: Actor, proposal_id: UUID, reason: str | None = None
) -> Approval:
    proposal = _locked_proposal(session, proposal_id)
    tenant_id = actor.tenant_id

    def deny(code: str, error: Exception) -> Exception:
        audit.record_denial(
            tenant_id, "human", actor.user_id, "proposal.approve", code, proposal_id=proposal_id
        )
        return error

    if proposal.status != "pending_approval":
        raise deny("not_pending", Conflict(f"Proposal is {proposal.status}, not pending approval"))
    if proposal.expires_at <= utcnow():
        raise deny("expired", Conflict("This proposal has expired."))

    # The current policy applies, even when the proposal was created under an older one.
    action = _action_type(session, proposal.action_type)
    policy = current_policy_version(session)
    if proposal.policy_version != policy:
        proposal.policy_version = policy
        proposal.risk = action.risk

    if not can_approve(actor, action.view_roles, action.approver_roles, proposal.target):
        raise deny("two_key_failed", PermissionDenied("You are not allowed to approve this."))
    if proposal.risk == "R3":
        if not actor.step_up_fresh:
            raise deny("step_up_required", StepUpRequired("Confirm your password to approve this."))
        if actor.user_id in {proposal.requested_by, proposal.last_edited_by}:
            raise deny("self_approval", PermissionDenied("You cannot approve your own request."))

    approval = Approval(
        tenant_id=tenant_id,
        proposal_id=proposal.id,
        payload_hash=proposal.payload_hash,
        decision="approved",
        approver_id=actor.user_id,
        approver_roles=sorted(actor.roles),
        reason=reason,
        step_up=actor.step_up_fresh,
        policy_version=policy,
        expires_at=utcnow() + APPROVAL_TTL,
    )
    session.add(approval)
    session.flush()
    proposal.status = "approved"
    audit.append(
        session,
        tenant_id,
        "human",
        actor.user_id,
        "proposal.approved",
        proposal_id=proposal.id,
        approval_id=approval.id,
        policy_version=policy,
        output_hash=proposal.payload_hash,
        reason=reason,
    )
    publish(
        session,
        tenant_id,
        ProposalApproved(
            proposal_id=proposal.id, approver_id=actor.user_id, action_type=proposal.action_type
        ),
    )
    return approval


def reject(session: Session, actor: Actor, proposal_id: UUID, reason: str) -> Approval:
    proposal = _locked_proposal(session, proposal_id)
    action = _action_type(session, proposal.action_type)
    if not reason.strip():
        raise ValidationFailed("A reason is required to reject")
    if not can_approve(actor, action.view_roles, action.approver_roles, proposal.target):
        audit.record_denial(
            actor.tenant_id,
            "human",
            actor.user_id,
            "proposal.reject",
            "two_key_failed",
            proposal_id=proposal_id,
        )
        raise PermissionDenied("You are not allowed to reject this.")
    if proposal.status not in {"pending_approval", "approved", "blocked"}:
        raise Conflict(f"Proposal is {proposal.status}")
    _void_active_approvals(session, proposal_id)
    approval = Approval(
        tenant_id=actor.tenant_id,
        proposal_id=proposal.id,
        payload_hash=proposal.payload_hash,
        decision="rejected",
        status="void",
        approver_id=actor.user_id,
        approver_roles=sorted(actor.roles),
        reason=reason,
        step_up=actor.step_up_fresh,
        policy_version=proposal.policy_version,
        expires_at=utcnow(),
    )
    session.add(approval)
    session.flush()
    proposal.status = "rejected"
    audit.append(
        session,
        actor.tenant_id,
        "human",
        actor.user_id,
        "proposal.rejected",
        proposal_id=proposal.id,
        approval_id=approval.id,
        reason=reason,
    )
    publish(
        session,
        actor.tenant_id,
        ProposalRejected(
            proposal_id=proposal.id, approver_id=actor.user_id, action_type=proposal.action_type
        ),
    )
    return approval


def _gate_failure(proposal: Proposal, session: Session, code: str) -> str:
    """Block the proposal for a person to review. Blocked work never retries by itself."""
    _void_active_approvals(session, proposal.id)
    proposal.status = "blocked"
    audit.append(
        session,
        proposal.tenant_id,
        "system",
        "executor",
        "execution.denied",
        "denied",
        reason=code,
        proposal_id=proposal.id,
        output_hash=proposal.payload_hash,
    )
    return code


def _approver_still_authorized(
    session: Session, approval: Approval, action: ActionType, target: dict[str, Any]
) -> bool:
    rows = session.scalars(
        select(RoleAssignment).where(RoleAssignment.user_id == approval.approver_id)
    ).all()
    from kernel.identity import RoleGrant

    actor = Actor(
        user_id=approval.approver_id,
        tenant_id=approval.tenant_id,
        grants=tuple(RoleGrant(r.role, r.scope_type, r.scope_id) for r in rows),
    )
    return can_approve(actor, action.view_roles, action.approver_roles, target)


def _claim(tenant_id: UUID, proposal_id: UUID, allowed_channel: str) -> dict[str, Any] | None:
    """All gate checks and the claim commit together, before anything leaves the system."""
    with tenant_session(tenant_id) as session:
        proposal = session.get(Proposal, proposal_id, with_for_update=True)
        if proposal is None or proposal.status != "approved":
            return None
        if proposal.channel != allowed_channel:
            return None
        action = _action_type(session, proposal.action_type)
        approval = session.scalar(
            select(Approval)
            .where(
                Approval.proposal_id == proposal.id,
                Approval.status == "active",
                Approval.decision == "approved",
            )
            .order_by(Approval.created_at.desc())
            .limit(1)
        )
        failure = None
        if approval is None:
            failure = "no_active_approval"
        elif approval.expires_at <= utcnow():
            failure = "approval_expired"
        elif payload_hash(proposal.payload) != proposal.payload_hash:
            failure = "payload_tampered"
        elif approval.payload_hash != proposal.payload_hash:
            failure = "hash_mismatch"
        elif approval.policy_version != current_policy_version(session):
            failure = "policy_changed"
        elif proposal.risk != action.risk:
            failure = "risk_changed"
        elif not _approver_still_authorized(session, approval, action, proposal.target):
            failure = "approver_not_authorized"
        elif action.risk == "R3" and (
            approval.approver_id in {proposal.requested_by, proposal.last_edited_by}
            or not approval.step_up
        ):
            failure = "separation_of_duties"
        if failure:
            _gate_failure(proposal, session, failure)
            return None

        execution = Execution(
            tenant_id=tenant_id,
            proposal_id=proposal.id,
            approval_id=approval.id,
            idempotency_key=proposal.idempotency_key,
            status="started",
        )
        session.add(execution)
        try:
            session.flush()
        except IntegrityError:
            raise Conflict("This action has already been executed") from None
        proposal.status = "executing"
        audit.append(
            session,
            tenant_id,
            "system",
            "executor",
            "execution.started",
            proposal_id=proposal.id,
            approval_id=approval.id,
            output_hash=proposal.payload_hash,
        )
        return {
            "execution_id": execution.id,
            "approval_id": approval.id,
            "payload": proposal.payload,
            "key": proposal.idempotency_key,
            "adapter": action.adapter,
            "action_type": action.id,
            "pack": action.pack,
            "target": proposal.target,
        }


def _finish(
    tenant_id: UUID,
    proposal_id: UUID,
    execution_id: UUID,
    status: str,
    provider_ref: str | None = None,
    error: str | None = None,
    claim: dict[str, Any] | None = None,
) -> None:
    with tenant_session(tenant_id) as session:
        execution = session.get(Execution, execution_id)
        proposal = session.get(Proposal, proposal_id, with_for_update=True)
        execution.status = status
        execution.provider_ref = provider_ref
        execution.error = error
        execution.finished_at = utcnow()
        proposal.status = {"succeeded": "executed", "failed": "failed", "unknown": "unknown"}[
            status
        ]
        audit.append(
            session,
            tenant_id,
            "system",
            "executor",
            f"execution.{status}",
            "success" if status == "succeeded" else "failure",
            proposal_id=proposal_id,
            approval_id=execution.approval_id,
            reason=error,
            data={"provider_ref": provider_ref} if provider_ref else {},
        )
        if status == "succeeded":
            publish(
                session,
                tenant_id,
                ActionExecuted(
                    proposal_id=proposal_id,
                    action_type=proposal.action_type,
                    pack=proposal.action_type.split(".", 1)[0],
                    execution_id=execution_id,
                    target=proposal.target,
                ),
            )


def execute(
    tenant_id: UUID,
    proposal_id: UUID,
    runner: Callable[[str | None, dict[str, Any], str], str | None],
    channel: str = "external",
) -> str:
    """Run an approved proposal. Returns the final status, or "skipped" if it wasn't runnable.

    runner(adapter, payload, idempotency_key) performs the effect and returns a provider ref.
    A process crash leaves the execution "started", and reconcile_stale() settles it.
    """
    with tracer.start_as_current_span(
        "trust.execute", attributes={"astra.proposal_id": str(proposal_id)}
    ):
        claim = _claim(tenant_id, proposal_id, channel)
        if claim is None:
            return "skipped"
        try:
            provider_ref = runner(claim["adapter"], claim["payload"], claim["key"])
        except AdapterRejected as exc:
            _finish(tenant_id, proposal_id, claim["execution_id"], "failed", error=str(exc))
            return "failed"
        except Exception as exc:  # noqa: BLE001 - outcome unknown: never retry blindly
            _finish(
                tenant_id,
                proposal_id,
                claim["execution_id"],
                "unknown",
                error=f"{type(exc).__name__}: {exc}"[:500],
            )
            return "unknown"
        _finish(tenant_id, proposal_id, claim["execution_id"], "succeeded", provider_ref)
        return "succeeded"


def reconcile_stale(
    tenant_id: UUID,
    lookup: Callable[[str | None, str], str | None],
    older_than: timedelta = STALE_EXECUTION,
) -> int:
    """Settle executions a crash left open, by asking the destination whether the effect happened.

    Found: mark it succeeded. Not found: mark it unknown, for a person to decide. Never resends.
    """
    cutoff = utcnow() - older_than
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            select(
                Execution.id, Execution.proposal_id, Execution.idempotency_key, Proposal.action_type
            )
            .join(Proposal, Proposal.id == Execution.proposal_id)
            .where(
                or_(
                    Execution.status == "unknown",
                    (Execution.status == "started") & (Execution.created_at <= cutoff),
                )
            )
        ).all()
        adapters = {r.action_type: _action_type(session, r.action_type).adapter for r in rows}
    for row in rows:
        ref = lookup(adapters[row.action_type], row.idempotency_key)
        if ref:
            _finish(tenant_id, row.proposal_id, row.id, "succeeded", ref)
        else:
            _finish(
                tenant_id, row.proposal_id, row.id, "unknown", error="No trace at the destination"
            )
    return len(rows)
