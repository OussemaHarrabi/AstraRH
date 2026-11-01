"""Add explicit run modes and employee scoping."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "finance_0008"
down_revision = "finance_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payroll_run",
        sa.Column("run_type", sa.String(length=16), nullable=False, server_default="regular"),
        schema="finance",
    )
    op.add_column(
        "payroll_run",
        sa.Column(
            "employee_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        schema="finance",
    )
    op.alter_column("payroll_run", "run_type", server_default=None, schema="finance")
    op.alter_column("payroll_run", "employee_ids", server_default=None, schema="finance")


def downgrade() -> None:
    op.drop_column("payroll_run", "employee_ids", schema="finance")
    op.drop_column("payroll_run", "run_type", schema="finance")