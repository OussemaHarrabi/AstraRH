"""Row-level security for inbox and calendar, and no double booking at the database level.

Revision ID: kernel_0003
Revises: ae38104e4ebd
"""

from alembic import op

from kernel.rls import enable_rls

revision = "kernel_0003"
down_revision = "ae38104e4ebd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    enable_rls(
        "comms.thread",
        "comms.message",
        "comms.classification",
        "comms.digest",
        "comms.digest_item",
        "calendar.busy_block",
        "calendar.booking",
        "calendar.booking_seat",
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist SCHEMA core")
    op.execute("SET LOCAL search_path TO core, public")
    # Even two simultaneous requests can't put one person in two meetings at the same time.
    op.execute(
        "ALTER TABLE calendar.booking_seat ADD CONSTRAINT no_double_booking "
        "EXCLUDE USING gist (tenant_id WITH =, participant WITH =, "
        "tstzrange(starts_at, ends_at) WITH &&)"
    )
    op.execute("SET LOCAL search_path TO public")


def downgrade() -> None:
    raise NotImplementedError("Security rules are not reversible. Wipe the database instead.")
