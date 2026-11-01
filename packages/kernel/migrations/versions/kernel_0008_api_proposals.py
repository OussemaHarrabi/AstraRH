"""Let the API role create proposals for human-initiated actions.

The worker already creates agent proposals. Endpoints such as "propose hiring this candidate"
or "propose booking this time" are human-initiated, so the API process must be able to insert
the proposal. It still cannot approve, execute, or edit an approval.

Revision ID: kernel_0008
Revises: 9afd7a1820d6
"""

from alembic import op

revision = "kernel_0008"
down_revision = "9afd7a1820d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT INSERT ON trust.proposal TO astra_api")


def downgrade() -> None:
    raise NotImplementedError("Security rules are not reversible. Wipe the database instead.")
