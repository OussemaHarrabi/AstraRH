"""workforce tables

Revision ID: workforce_0001
Revises:

Mirrors packages/packs/workforce/models.py. On a running stack, confirm/regenerate
with `python astra.py makemigration workforce "workforce tables"`.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "workforce_0001"
down_revision = None
branch_labels = ("workforce",)
depends_on = "kernel_0002"


def _common() -> list[sa.Column]:
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "leave_type",
        sa.Column("external_id", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("needs_coverage", sa.Boolean(), nullable=False),
        *_common(),
        sa.ForeignKeyConstraint(["tenant_id"], ["core.tenant.id"], name=op.f("fk_leave_type_tenant_id_tenant")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leave_type")),
        sa.UniqueConstraint("tenant_id", "external_id", name=op.f("uq_leave_type_tenant_id_external_id")),
        schema="workforce",
    )

    op.create_table(
        "leave_balance",
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("leave_type_id", sa.UUID(), nullable=False),
        sa.Column("days_remaining", sa.Numeric(precision=5, scale=1), nullable=False),
        *_common(),
        sa.ForeignKeyConstraint(["employee_id"], ["core.employee.id"], name=op.f("fk_leave_balance_employee_id_employee")),
        sa.ForeignKeyConstraint(["leave_type_id"], ["workforce.leave_type.id"], name=op.f("fk_leave_balance_leave_type_id_leave_type")),
        sa.ForeignKeyConstraint(["tenant_id"], ["core.tenant.id"], name=op.f("fk_leave_balance_tenant_id_tenant")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leave_balance")),
        sa.UniqueConstraint("tenant_id", "employee_id", "leave_type_id", name=op.f("uq_leave_balance_tenant_id_employee_id_leave_type_id")),
        schema="workforce",
    )
    op.create_index(op.f("ix_leave_balance_employee_id"), "leave_balance", ["employee_id"], unique=False, schema="workforce")

    op.create_table(
        "leave_request",
        sa.Column("external_id", sa.String(length=32), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("leave_type_id", sa.UUID(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("clash_of", postgresql.ARRAY(sa.String()), nullable=True),
        *_common(),
        sa.ForeignKeyConstraint(["employee_id"], ["core.employee.id"], name=op.f("fk_leave_request_employee_id_employee")),
        sa.ForeignKeyConstraint(["leave_type_id"], ["workforce.leave_type.id"], name=op.f("fk_leave_request_leave_type_id_leave_type")),
        sa.ForeignKeyConstraint(["tenant_id"], ["core.tenant.id"], name=op.f("fk_leave_request_tenant_id_tenant")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leave_request")),
        sa.UniqueConstraint("tenant_id", "external_id", name=op.f("uq_leave_request_tenant_id_external_id")),
        schema="workforce",
    )
    op.create_index(op.f("ix_leave_request_employee_id"), "leave_request", ["employee_id"], unique=False, schema="workforce")

    op.create_table(
        "shift",
        sa.Column("external_id", sa.String(length=32), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("org_unit_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("start_min", sa.Integer(), nullable=False),
        sa.Column("end_min", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        *_common(),
        sa.ForeignKeyConstraint(["employee_id"], ["core.employee.id"], name=op.f("fk_shift_employee_id_employee")),
        sa.ForeignKeyConstraint(["org_unit_id"], ["core.org_unit.id"], name=op.f("fk_shift_org_unit_id_org_unit")),
        sa.ForeignKeyConstraint(["tenant_id"], ["core.tenant.id"], name=op.f("fk_shift_tenant_id_tenant")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shift")),
        sa.UniqueConstraint("tenant_id", "external_id", name=op.f("uq_shift_tenant_id_external_id")),
        schema="workforce",
    )
    op.create_index(op.f("ix_shift_employee_id"), "shift", ["employee_id"], unique=False, schema="workforce")
    op.create_index(op.f("ix_shift_org_unit_id"), "shift", ["org_unit_id"], unique=False, schema="workforce")

    op.create_table(
        "time_entry",
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("org_unit_id", sa.UUID(), nullable=False),
        sa.Column("week", sa.String(length=10), nullable=False),
        sa.Column("hours", sa.Numeric(precision=5, scale=1), nullable=False),
        *_common(),
        sa.ForeignKeyConstraint(["employee_id"], ["core.employee.id"], name=op.f("fk_time_entry_employee_id_employee")),
        sa.ForeignKeyConstraint(["org_unit_id"], ["core.org_unit.id"], name=op.f("fk_time_entry_org_unit_id_org_unit")),
        sa.ForeignKeyConstraint(["tenant_id"], ["core.tenant.id"], name=op.f("fk_time_entry_tenant_id_tenant")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_time_entry")),
        schema="workforce",
    )
    op.create_index(op.f("ix_time_entry_employee_id"), "time_entry", ["employee_id"], unique=False, schema="workforce")
    op.create_index(op.f("ix_time_entry_org_unit_id"), "time_entry", ["org_unit_id"], unique=False, schema="workforce")

    op.create_table(
        "capacity_snapshot",
        sa.Column("org_unit_id", sa.UUID(), nullable=False),
        sa.Column("week", sa.String(length=10), nullable=False),
        sa.Column("headcount", sa.Integer(), nullable=False),
        sa.Column("scheduled_hours", sa.Numeric(precision=7, scale=1), nullable=False),
        sa.Column("actual_hours", sa.Numeric(precision=7, scale=1), nullable=False),
        sa.Column("overtime_hours", sa.Numeric(precision=7, scale=1), nullable=False),
        sa.Column("on_leave_count", sa.Integer(), nullable=False),
        sa.Column("open_reqs", sa.Integer(), nullable=False),
        *_common(),
        sa.ForeignKeyConstraint(["org_unit_id"], ["core.org_unit.id"], name=op.f("fk_capacity_snapshot_org_unit_id_org_unit")),
        sa.ForeignKeyConstraint(["tenant_id"], ["core.tenant.id"], name=op.f("fk_capacity_snapshot_tenant_id_tenant")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capacity_snapshot")),
        sa.UniqueConstraint("tenant_id", "org_unit_id", "week", name=op.f("uq_capacity_snapshot_tenant_id_org_unit_id_week")),
        schema="workforce",
    )
    op.create_index(op.f("ix_capacity_snapshot_org_unit_id"), "capacity_snapshot", ["org_unit_id"], unique=False, schema="workforce")

    op.create_table(
        "case",
        sa.Column("external_id", sa.String(length=32), nullable=False),
        sa.Column("org_unit_id", sa.UUID(), nullable=False),
        sa.Column("case_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("opened_by", sa.UUID(), nullable=False),
        *_common(),
        sa.ForeignKeyConstraint(["opened_by"], ["core.employee.id"], name=op.f("fk_case_opened_by_employee")),
        sa.ForeignKeyConstraint(["org_unit_id"], ["core.org_unit.id"], name=op.f("fk_case_org_unit_id_org_unit")),
        sa.ForeignKeyConstraint(["tenant_id"], ["core.tenant.id"], name=op.f("fk_case_tenant_id_tenant")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case")),
        sa.UniqueConstraint("tenant_id", "external_id", name=op.f("uq_case_tenant_id_external_id")),
        schema="workforce",
    )
    op.create_index(op.f("ix_case_org_unit_id"), "case", ["org_unit_id"], unique=False, schema="workforce")

    op.create_table(
        "case_party",
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        *_common(),
        sa.ForeignKeyConstraint(["case_id"], ["workforce.case.id"], name=op.f("fk_case_party_case_id_case")),
        sa.ForeignKeyConstraint(["employee_id"], ["core.employee.id"], name=op.f("fk_case_party_employee_id_employee")),
        sa.ForeignKeyConstraint(["tenant_id"], ["core.tenant.id"], name=op.f("fk_case_party_tenant_id_tenant")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_party")),
        sa.UniqueConstraint("tenant_id", "case_id", "employee_id", name=op.f("uq_case_party_tenant_id_case_id_employee_id")),
        schema="workforce",
    )
    op.create_index(op.f("ix_case_party_case_id"), "case_party", ["case_id"], unique=False, schema="workforce")

    op.create_table(
        "case_event",
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_common(),
        sa.ForeignKeyConstraint(["case_id"], ["workforce.case.id"], name=op.f("fk_case_event_case_id_case")),
        sa.ForeignKeyConstraint(["tenant_id"], ["core.tenant.id"], name=op.f("fk_case_event_tenant_id_tenant")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_event")),
        schema="workforce",
    )
    op.create_index(op.f("ix_case_event_case_id"), "case_event", ["case_id"], unique=False, schema="workforce")

    op.create_table(
        "resolution_plan",
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_citations", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_common(),
        sa.ForeignKeyConstraint(["case_id"], ["workforce.case.id"], name=op.f("fk_resolution_plan_case_id_case")),
        sa.ForeignKeyConstraint(["tenant_id"], ["core.tenant.id"], name=op.f("fk_resolution_plan_tenant_id_tenant")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resolution_plan")),
        schema="workforce",
    )
    op.create_index(op.f("ix_resolution_plan_case_id"), "resolution_plan", ["case_id"], unique=False, schema="workforce")


def downgrade() -> None:
    for table in [
        "resolution_plan", "case_event", "case_party", "case",
        "capacity_snapshot", "time_entry", "shift", "leave_request",
        "leave_balance", "leave_type",
    ]:
        op.drop_table(table, schema="workforce")
