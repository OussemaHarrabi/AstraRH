"""Row-level security on every talent table.

Revision ID: talent_0002
Revises: 0843fca3e74f
"""

from kernel.rls import enable_rls

revision = "talent_0002"
down_revision = "0843fca3e74f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    enable_rls(
        "talent.job",
        "talent.rubric",
        "talent.candidate",
        "talent.candidate_identity",
        "talent.application",
        "talent.stage_event",
        "talent.cv_document",
        "talent.cv_chunk",
        "talent.extracted_profile",
        "talent.ranking_run",
        "talent.score",
        "talent.criterion_override",
    )


def downgrade() -> None:
    raise NotImplementedError("Security rules are not reversible. Wipe the database instead.")
