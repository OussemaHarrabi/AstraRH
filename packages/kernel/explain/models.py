from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db import Base, TenantMixin


class DecisionRecord(TenantMixin, Base):
    """Immutable. Database triggers forbid UPDATE and DELETE."""

    __tablename__ = "decision_record"
    __table_args__ = {"schema": "trust"}

    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    outcome: Mapped[dict] = mapped_column(JSONB, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    rationale: Mapped[str | None] = mapped_column(Text)
    narrative: Mapped[str | None] = mapped_column(Text)
    scorer: Mapped[str | None] = mapped_column(String(128))
    scorer_version: Mapped[str | None] = mapped_column(String(64))
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    not_considered: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    limits: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    view_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    trace_id: Mapped[str | None] = mapped_column(String(32))


class DecisionFactor(TenantMixin, Base):
    __tablename__ = "decision_factor"
    __table_args__ = {"schema": "trust"}

    record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trust.decision_record.id"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    contribution: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class DecisionEvidence(TenantMixin, Base):
    __tablename__ = "decision_evidence"
    __table_args__ = {"schema": "trust"}

    record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trust.decision_record.id"), nullable=False, index=True
    )
    ref: Mapped[str] = mapped_column(String(128), nullable=False)
    factor_key: Mapped[str | None] = mapped_column(String(128))
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    locator: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    quote: Mapped[str] = mapped_column(Text, nullable=False)


class DecisionCounterfactual(TenantMixin, Base):
    __tablename__ = "decision_counterfactual"
    __table_args__ = {"schema": "trust"}

    record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trust.decision_record.id"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    change: Mapped[dict] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[dict] = mapped_column(JSONB, nullable=False)
