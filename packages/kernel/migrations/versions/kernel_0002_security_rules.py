"""Row-level security, role permissions, immutability triggers, jobs schema.

Revision ID: kernel_0002
Revises: e354e5b41221
"""

from pathlib import Path

from alembic import op

from kernel.jobs import schema_sql
from kernel.rls import enable_rls

revision = "kernel_0002"
down_revision = "e354e5b41221"
branch_labels = None
depends_on = None

RULES = Path(__file__).resolve().parents[1] / "rules"

TENANT_TABLES = (
    "core.user_account",
    "core.role_assignment",
    "core.login_attempt",
    "core.person",
    "core.org_unit",
    "core.position",
    "core.employee",
    "core.skill",
    "core.skill_relation",
    "core.person_skill_evidence",
    "core.kpi_definition",
    "core.kpi_observation",
    "core.event_outbox",
    "core.event_delivery",
    "trust.approval",
    "trust.execution",
    "trust.audit_event",
    "trust.decision_record",
    "trust.decision_factor",
    "trust.decision_evidence",
    "trust.decision_counterfactual",
    "ai.agent_run",
    "ai.agent_step",
    "ai.prompt_version",
    "ai.llm_cache",
    "ai.security_event",
    "ai.eval_result",
)

# The executor can't see a proposal until it has reached approval: drafts stay private.
EXECUTOR_VISIBLE = "('approved','executing','executed','failed','unknown','blocked')"


def _run_sql(sql: str) -> None:
    """Whole SQL files, on the migration's own transaction, with no parameter processing."""
    op.get_bind().connection.driver_connection.execute(sql)


def upgrade() -> None:
    _run_sql((RULES / "security.sql").read_text(encoding="utf-8"))
    enable_rls(*TENANT_TABLES)

    op.execute("ALTER TABLE trust.proposal ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE trust.proposal FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON trust.proposal "
        "TO astra_owner, astra_api, astra_worker "
        "USING (tenant_id = core.current_tenant()) "
        "WITH CHECK (tenant_id = core.current_tenant())"
    )
    op.execute(
        "CREATE POLICY executor_read ON trust.proposal FOR SELECT TO astra_executor "
        f"USING (tenant_id = core.current_tenant() AND status IN {EXECUTOR_VISIBLE})"
    )
    op.execute(
        "CREATE POLICY executor_update ON trust.proposal FOR UPDATE TO astra_executor "
        f"USING (tenant_id = core.current_tenant() AND status IN {EXECUTOR_VISIBLE}) "
        f"WITH CHECK (tenant_id = core.current_tenant() AND status IN {EXECUTOR_VISIBLE})"
    )

    _run_sql("SET LOCAL search_path TO jobs")
    _run_sql(schema_sql())
    _run_sql("SET LOCAL search_path TO public")
    _run_sql((RULES / "after_jobs.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("Security rules are not reversible. Wipe the database instead.")
