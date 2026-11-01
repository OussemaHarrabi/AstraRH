"""Row-level security on calendar holds.

Revision ID: kernel_0006
Revises: d168b9f5912c
"""

from kernel.rls import enable_rls

revision = "kernel_0006"
down_revision = "d168b9f5912c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    enable_rls("calendar.hold")


def downgrade() -> None:
    raise NotImplementedError("Security rules are not reversible. Wipe the database instead.")
