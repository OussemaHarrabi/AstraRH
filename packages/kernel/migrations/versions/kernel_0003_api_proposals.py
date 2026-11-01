"""Allow the authenticated API role to create human-initiated proposals.

The API could already write DecisionRecords but not their Proposal, so any
human-initiated R2 action (talent rejection, journey milestone verification,
support-flag notification) failed at the trust boundary.
"""

from alembic import op

revision = "kernel_0003"
down_revision = "kernel_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT INSERT ON trust.proposal TO astra_api")


def downgrade() -> None:
    op.execute("REVOKE INSERT ON trust.proposal FROM astra_api")
