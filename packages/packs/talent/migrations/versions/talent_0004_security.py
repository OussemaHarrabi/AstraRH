"""Row-level security on follow-ups and interviews.

Revision ID: talent_0004
Revises: 5d85161ca2dc
"""

from kernel.rls import enable_rls

revision = "talent_0004"
down_revision = "5d85161ca2dc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    enable_rls("talent.followup", "talent.interview")


def downgrade() -> None:
    raise NotImplementedError("Security rules are not reversible. Wipe the database instead.")
