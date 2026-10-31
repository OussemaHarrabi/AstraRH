from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db import Base, TenantMixin, utcnow


class ActionType(Base):
    """Global catalogue synced from pack manifests. An action not listed here cannot run."""

    __tablename__ = "action_type"
    __table_args__ = {"schema": "trust"}

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    pack: Mapped[str] = mapped_column(String(32), nullable=False)
    risk: Mapped[str] = mapped_column(String(2), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    adapter: Mapped[str | None] = mapped_column(String(64))
    approver_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    view_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class PolicyVersion(Base):
    """Hash of the action catalogue. Approval under an older policy is re-evaluated."""

    __tablename__ = "policy_version"
    __table_args__ = {"schema": "trust"}

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Proposal(TenantMixin, Base):
    __tablename__ = "proposal"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"), {"schema": "trust"})

    action_type: Mapped[str] = mapped_column(
        String(128), ForeignKey("trust.action_type.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    risk: Mapped[str] = mapped_column(String(2), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    decision_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    agent_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    requested_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    last_edited_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class Approval(TenantMixin, Base):
    """A human decision, bound to the exact payload hash. Editing the payload voids it."""

    __tablename__ = "approval"
    __table_args__ = {"schema": "trust"}

    proposal_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trust.proposal.id"), nullable=False, index=True
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    approver_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    approver_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    step_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Execution(TenantMixin, Base):
    """Claimed before the outside call. The unique key makes a duplicate execution impossible."""

    __tablename__ = "execution"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"), {"schema": "trust"})

    proposal_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trust.proposal.id"), nullable=False, index=True
    )
    approval_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trust.approval.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(TenantMixin, Base):
    """Append-only, hash-chained per tenant. Database triggers forbid UPDATE and DELETE."""

    __tablename__ = "audit_event"
    __table_args__ = (UniqueConstraint("tenant_id", "seq"), {"schema": "trust"})

    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    proposal_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    approval_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    policy_version: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(128))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    input_hash: Mapped[str | None] = mapped_column(String(64))
    output_hash: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
