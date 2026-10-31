from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db import Base, TenantMixin

UUID_TYPE = PG_UUID(as_uuid=True)
MONEY = Numeric(18, 3)
RATE = Numeric(9, 6)
SCHEMA = {"schema": "finance"}


class Engagement(TenantMixin, Base):
    """A person's employment or placement. A CIVP and a later CDI are separate rows."""

    __tablename__ = "engagement"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_request_id"),
        UniqueConstraint("tenant_id", "source_event_id"),
        Index("ix_engagement_employee", "employee_id"),
        SCHEMA,
    )

    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date | None] = mapped_column(Date)
    job_title: Mapped[str] = mapped_column(Text, nullable=False)
    work_location: Mapped[str | None] = mapped_column(String(128))
    weekly_hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    cdd_reason_code: Mapped[str | None] = mapped_column(String(64))
    head_of_family: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    children: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    external_request_id: Mapped[str | None] = mapped_column(String(128))
    source_event_id: Mapped[str | None] = mapped_column(String(128))
    linked_engagement_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("finance.engagement.id")
    )
    activated_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EngagementAmendment(TenantMixin, Base):
    """A change with an effective date. Earlier values are never overwritten."""

    __tablename__ = "engagement_amendment"
    __table_args__ = SCHEMA

    engagement_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.engagement.id"), nullable=False, index=True
    )
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)


class PayItem(TenantMixin, Base):
    __tablename__ = "pay_item"
    __table_args__ = (UniqueConstraint("engagement_id", "code", "valid_from"), SCHEMA)

    engagement_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.engagement.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="TND")
    frequency: Mapped[str] = mapped_column(String(16), nullable=False, default="monthly")
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)


class DocumentRef(TenantMixin, Base):
    """A reference to a stored document and its verification. Never the file itself."""

    __tablename__ = "document_ref"
    __table_args__ = SCHEMA

    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False, index=True
    )
    engagement_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("finance.engagement.id"), index=True
    )
    doc_type: Mapped[str] = mapped_column(String(48), nullable=False)
    file_key: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    verified_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class ValidationIssue(TenantMixin, Base):
    """What blocks or needs a human, with who should act and what to do next."""

    __tablename__ = "validation_issue"
    __table_args__ = (Index("ix_validation_issue_entity", "entity_type", "entity_id"), SCHEMA)

    entity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    field: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    next_action: Mapped[str | None] = mapped_column(Text)
    owner_role: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open")
    resolved_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_reason: Mapped[str | None] = mapped_column(Text)


class CivpPlacement(TenantMixin, Base):
    __tablename__ = "civp_placement"
    __table_args__ = (UniqueConstraint("engagement_id"), SCHEMA)

    engagement_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.engagement.id"), nullable=False
    )
    aneti_reference: Mapped[str | None] = mapped_column(String(64))
    approval_status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    participant_category: Mapped[str] = mapped_column(String(48), nullable=False)
    disabled_participant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    aneti_allowance_monthly: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    employer_complement_monthly: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    training_hours_limit: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    eligibility_confirmed_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    eligibility_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CivpLedgerEntry(TenantMixin, Base):
    """One row per placement, month and payer. The two payers are never merged."""

    __tablename__ = "civp_ledger_entry"
    __table_args__ = (UniqueConstraint("placement_id", "month", "payer"), SCHEMA)

    placement_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.civp_placement.id"), nullable=False, index=True
    )
    month: Mapped[date] = mapped_column(Date, nullable=False)
    payer: Mapped[str] = mapped_column(String(10), nullable=False)
    due_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="due")
    payment_ref: Mapped[str | None] = mapped_column(String(128))


class CivpTraining(TenantMixin, Base):
    __tablename__ = "civp_training"
    __table_args__ = SCHEMA

    placement_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.civp_placement.id"), nullable=False, index=True
    )
    training_date: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_by: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)


class CivpExtensionRequest(TenantMixin, Base):
    __tablename__ = "civp_extension_request"
    __table_args__ = SCHEMA

    placement_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.civp_placement.id"), nullable=False, index=True
    )
    requested_end: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    decided_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)


class RuleSetRecord(TenantMixin, Base):
    """A stored, versioned rule set. Past runs name the set that produced them."""

    __tablename__ = "rule_set"
    __table_args__ = (UniqueConstraint("tenant_id", "rule_id"), SCHEMA)

    rule_id: Mapped[str] = mapped_column(String(96), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="payroll")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft")
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmployerProfile(TenantMixin, Base):
    __tablename__ = "employer_profile"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"), SCHEMA)

    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    legal_entity: Mapped[str] = mapped_column(Text, nullable=False)
    sector: Mapped[str | None] = mapped_column(String(64))
    regime_id: Mapped[str] = mapped_column(String(64), nullable=False)
    identifiers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class PayrollInputBatch(TenantMixin, Base):
    __tablename__ = "payroll_input_batch"
    __table_args__ = (UniqueConstraint("tenant_id", "file_sha256"), SCHEMA)

    source: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="received")
    received_event_id: Mapped[str | None] = mapped_column(String(128))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    submitted_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    accepted_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PayrollInput(TenantMixin, Base):
    """The unique source id means the same input arriving twice is stored once."""

    __tablename__ = "payroll_input"
    __table_args__ = (UniqueConstraint("tenant_id", "source_event_id"), SCHEMA)

    batch_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.payroll_input_batch.id"), nullable=False, index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="accepted")
    reject_reason: Mapped[str | None] = mapped_column(Text)


class PayrollRun(TenantMixin, Base):
    __tablename__ = "payroll_run"
    __table_args__ = (UniqueConstraint("tenant_id", "external_request_id"), SCHEMA)

    external_request_id: Mapped[str | None] = mapped_column(String(128))
    employer_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("finance.employer_profile.id")
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    pay_date: Mapped[date] = mapped_column(Date, nullable=False)
    regime_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    rule_set_refs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    input_batch_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    inputs_hash: Mapped[str | None] = mapped_column(String(64))
    results_hash: Mapped[str | None] = mapped_column(String(64))
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prepared_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    last_edited_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    approval_proposal_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)


class Payslip(TenantMixin, Base):
    __tablename__ = "payslip"
    __table_args__ = (UniqueConstraint("run_id", "employee_id"), SCHEMA)

    run_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.payroll_run.id"), nullable=False, index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False, index=True
    )
    engagement_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.engagement.id"), nullable=False
    )
    gross: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    employee_deductions: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    income_tax: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    solidarity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    net_pay: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    employer_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    decision_record_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)


class PayslipLine(TenantMixin, Base):
    __tablename__ = "payslip_line"
    __table_args__ = (UniqueConstraint("payslip_id", "position"), SCHEMA)

    payslip_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.payslip.id"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(48), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    base: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rate: Mapped[Decimal | None] = mapped_column(RATE)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    rule_ref: Mapped[str] = mapped_column(Text, nullable=False)


class Adjustment(TenantMixin, Base):
    """A correction in a later run for a change effective in a closed period."""

    __tablename__ = "adjustment"
    __table_args__ = SCHEMA

    run_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.payroll_run.id"), nullable=False, index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False
    )
    origin_run_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("finance.payroll_run.id")
    )
    amendment_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("finance.engagement_amendment.id")
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class PaymentBatch(TenantMixin, Base):
    """One approved release. The unique execution id makes a duplicate delivery harmless."""

    __tablename__ = "payment_batch"
    __table_args__ = (
        UniqueConstraint("run_id", "release_number"),
        UniqueConstraint("tenant_id", "execution_id"),
        SCHEMA,
    )

    run_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.payroll_run.id"), nullable=False, index=True
    )
    release_number: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="submitted")


class PaymentLine(TenantMixin, Base):
    __tablename__ = "payment_line"
    __table_args__ = (
        UniqueConstraint("payslip_id"),
        UniqueConstraint("tenant_id", "idempotency_key"),
        SCHEMA,
    )

    run_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.payroll_run.id"), nullable=False, index=True
    )
    payslip_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.payslip.id"), nullable=False
    )
    batch_id: Mapped[UUID | None] = mapped_column(UUID_TYPE, ForeignKey("finance.payment_batch.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="due")
    bank_ref_token: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    last_status_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_reason: Mapped[str | None] = mapped_column(String(64))


class PaymentStatusEvent(TenantMixin, Base):
    """Append-only history of what the bank reported, so a redelivery changes nothing."""

    __tablename__ = "payment_status_event"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_ref", "payment_line_id", "status_seq"),
        SCHEMA,
    )

    payment_line_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("finance.payment_line.id"), nullable=False, index=True
    )
    provider_ref: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    status_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_matches: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HireNotice(TenantMixin, Base):
    """A candidate reached 'hired'. HR completes it with the employee and the terms."""

    __tablename__ = "hire_notice"
    __table_args__ = (UniqueConstraint("tenant_id", "application_id"), SCHEMA)

    application_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    job_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="awaiting_terms")
    engagement_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("finance.engagement.id")
    )
    source_event_id: Mapped[str | None] = mapped_column(String(128))
