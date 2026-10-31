"""Workforce tables (schema `workforce`).

Invariants honoured:
  * Every table carries `tenant_id` under RLS (via TenantMixin).  (inv. 9)
  * Foreign keys point only into `core` or within `workforce` — never into
    another pack.  (inv. 8)
  * Capacity is stored per team x week only: there is no per-person
    performance or conflict column anywhere.  (ARCHITECTURE: what we will not build)

`id`, `created_at` and `tenant_id` come from Base / TenantMixin, as in the
other packs, so they are not redeclared here.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
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


# --- tracking -------------------------------------------------------------

class LeaveType(TenantMixin, Base):
    __tablename__ = "leave_type"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"), {"schema": "workforce"})

    external_id: Mapped[str] = mapped_column(String(32), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    needs_coverage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class LeaveBalance(TenantMixin, Base):
    __tablename__ = "leave_balance"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_id", "leave_type_id"),
        {"schema": "workforce"},
    )

    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False, index=True
    )
    leave_type_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("workforce.leave_type.id"), nullable=False
    )
    days_remaining: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)


class LeaveRequest(TenantMixin, Base):
    __tablename__ = "leave_request"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"), {"schema": "workforce"})

    external_id: Mapped[str] = mapped_column(String(32), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False, index=True
    )
    leave_type_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("workforce.leave_type.id"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    note: Mapped[str | None] = mapped_column(Text)
    # external_ids of requests this one clashes with (coverage conflict), set by the clash check
    clash_of: Mapped[list | None] = mapped_column(ARRAY(String))


class Shift(TenantMixin, Base):
    __tablename__ = "shift"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"), {"schema": "workforce"})

    external_id: Mapped[str] = mapped_column(String(32), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False, index=True
    )
    org_unit_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.org_unit.id"), nullable=False, index=True
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    start_min: Mapped[int] = mapped_column(Integer, nullable=False)  # minutes from midnight
    end_min: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="support")


class TimeEntry(TenantMixin, Base):
    __tablename__ = "time_entry"
    __table_args__ = {"schema": "workforce"}

    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False, index=True
    )
    org_unit_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.org_unit.id"), nullable=False, index=True
    )
    week: Mapped[str] = mapped_column(String(10), nullable=False)  # ISO week, e.g. 2026-W43
    hours: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)


class CapacitySnapshot(TenantMixin, Base):
    """Team x week totals — the only grain. No per-person row exists by design."""

    __tablename__ = "capacity_snapshot"
    __table_args__ = (
        UniqueConstraint("tenant_id", "org_unit_id", "week"),
        {"schema": "workforce"},
    )

    org_unit_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.org_unit.id"), nullable=False, index=True
    )
    week: Mapped[str] = mapped_column(String(10), nullable=False)
    headcount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_hours: Mapped[Decimal] = mapped_column(Numeric(7, 1), nullable=False, default=0)
    actual_hours: Mapped[Decimal] = mapped_column(Numeric(7, 1), nullable=False, default=0)
    overtime_hours: Mapped[Decimal] = mapped_column(Numeric(7, 1), nullable=False, default=0)
    on_leave_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_reqs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# --- conflict management --------------------------------------------------

class Case(TenantMixin, Base):
    """Confidential conflict case. Metadata only; sensitive text lives in
    CaseEvent rows. Access is enforced through CaseParty, not just the UI.
    Cases are never projected into the graph database."""

    __tablename__ = "case"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"), {"schema": "workforce"})

    external_id: Mapped[str] = mapped_column(String(32), nullable=False)
    org_unit_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.org_unit.id"), nullable=False, index=True
    )
    case_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="opened")
    opened_by: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False
    )


class CaseParty(TenantMixin, Base):
    """Who may see a case: its named parties and the assigned mediator."""

    __tablename__ = "case_party"
    __table_args__ = (
        UniqueConstraint("tenant_id", "case_id", "employee_id"),
        {"schema": "workforce"},
    )

    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("workforce.case.id"), nullable=False, index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # party | mediator


class CaseEvent(TenantMixin, Base):
    """Append-only log of everything that happened on a case (intake, summary,
    suggested process, mediation notes, resolution)."""

    __tablename__ = "case_event"
    __table_args__ = {"schema": "workforce"}

    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("workforce.case.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ResolutionPlan(TenantMixin, Base):
    __tablename__ = "resolution_plan"
    __table_args__ = {"schema": "workforce"}

    case_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("workforce.case.id"), nullable=False, index=True
    )
    steps: Mapped[list] = mapped_column(JSONB, nullable=False)
    policy_citations: Mapped[list | None] = mapped_column(ARRAY(String))
    outcome: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="suggested")
