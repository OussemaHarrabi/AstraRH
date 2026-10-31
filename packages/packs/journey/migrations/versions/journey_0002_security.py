"""Row-level security on every journey table.

Revision ID: journey_0002
Revises: journey_0001
"""

from kernel.rls import enable_rls

revision = "journey_0002"
down_revision = "journey_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    enable_rls(
        "journey.onboarding_template",
        "journey.template_task",
        "journey.onboarding_plan",
        "journey.onboarding_task",
        "journey.buddy_assignment",
        "journey.checkin",
        "journey.pulse_survey",
        "journey.pulse_response",
        "journey.support_flag",
        "journey.skill_requirement",
        "journey.skill_gap",
        "journey.course",
        "journey.training_recommendation",
        "journey.enrollment",
        "journey.impact_measure",
    )


def downgrade() -> None:
    raise NotImplementedError("Security rules are not reversible. Wipe the database instead.")
