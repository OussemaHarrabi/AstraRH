"""Widen decision evidence references.

Pack evidence uses stable references such as ``plan:<uuid>``. They are identifiers, not the
short ``E1`` citation labels, and can be longer than 16 characters.

Revision ID: kernel_0009
Revises: kernel_0008
"""

import sqlalchemy as sa
from alembic import op

revision = "kernel_0009"
down_revision = "kernel_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "decision_evidence",
        "ref",
        existing_type=sa.String(length=16),
        type_=sa.String(length=128),
        existing_nullable=False,
        schema="trust",
    )


def downgrade() -> None:
    raise NotImplementedError("Security rules are not reversible. Wipe the database instead.")
