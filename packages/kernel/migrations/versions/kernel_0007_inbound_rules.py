"""Row-level security on inbound mail, and who may touch it.

The executor copies raw mail in: it may insert and read the provider id back (to skip what it
already has), never the content. The api never needs raw mail, so it loses access. The worker
reads and parses it.

Revision ID: kernel_0007
Revises: 5296b9b782c3
"""

from alembic import op

from kernel.rls import enable_rls

revision = "kernel_0007"
down_revision = "5296b9b782c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    enable_rls("comms.inbound_mail", "comms.attachment")
    op.execute("REVOKE ALL ON comms.inbound_mail FROM astra_api")
    op.execute("GRANT USAGE ON SCHEMA comms TO astra_executor")
    op.execute("GRANT INSERT ON comms.inbound_mail TO astra_executor")
    op.execute("GRANT SELECT (tenant_id, provider_id) ON comms.inbound_mail TO astra_executor")


def downgrade() -> None:
    raise NotImplementedError("Security rules are not reversible. Wipe the database instead.")
