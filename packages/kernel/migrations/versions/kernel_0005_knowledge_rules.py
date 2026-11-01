"""Row-level security on company documents and questions.

Revision ID: kernel_0005
Revises: b83efbe1d77d
"""

from kernel.rls import enable_rls

revision = "kernel_0005"
down_revision = "b83efbe1d77d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    enable_rls("knowledge.document", "knowledge.chunk", "knowledge.question", "knowledge.ticket")


def downgrade() -> None:
    raise NotImplementedError("Security rules are not reversible. Wipe the database instead.")
