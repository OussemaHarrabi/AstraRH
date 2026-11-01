"""Row-level security for input rejections, and guards on inputs and batches.

An input is withdrawn, never edited or deleted. A batch keeps its period and its content hash.
A rejection is history. These hold for every role, the owner included.

Revision ID: finance_0005
Revises: df4c291a2cdf
"""

from alembic import op

from kernel.rls import enable_rls

revision = "finance_0005"
down_revision = "df4c291a2cdf"
branch_labels = None
depends_on = None

RULES = """
CREATE FUNCTION finance.guard_payroll_input() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'An input is withdrawn, never deleted';
  END IF;
  IF (NEW.batch_id, NEW.employee_id, NEW.kind, NEW.quantity, NEW.amount, NEW.effective_date,
      NEW.reference, NEW.line_number, NEW.source_event_id)
     IS DISTINCT FROM
     (OLD.batch_id, OLD.employee_id, OLD.kind, OLD.quantity, OLD.amount, OLD.effective_date,
      OLD.reference, OLD.line_number, OLD.source_event_id) THEN
    RAISE EXCEPTION 'The content of an input cannot be changed';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status
     AND (OLD.status, NEW.status) NOT IN (('accepted', 'withdrawn')) THEN
    RAISE EXCEPTION 'An input cannot go from % to %', OLD.status, NEW.status;
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER payroll_input_guarded
  BEFORE UPDATE OR DELETE ON finance.payroll_input
  FOR EACH ROW EXECUTE FUNCTION finance.guard_payroll_input();

CREATE FUNCTION finance.guard_input_batch() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'An input batch is never deleted';
  END IF;
  IF (NEW.source, NEW.period_start, NEW.period_end, NEW.file_sha256, NEW.submitted_by)
     IS DISTINCT FROM
     (OLD.source, OLD.period_start, OLD.period_end, OLD.file_sha256, OLD.submitted_by) THEN
    RAISE EXCEPTION 'The source, period and content of an input batch cannot be changed';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER payroll_input_batch_guarded
  BEFORE UPDATE OR DELETE ON finance.payroll_input_batch
  FOR EACH ROW EXECUTE FUNCTION finance.guard_input_batch();

CREATE TRIGGER payroll_input_rejection_append_only
  BEFORE UPDATE OR DELETE ON finance.payroll_input_rejection
  FOR EACH ROW EXECUTE FUNCTION finance.forbid_change();
"""

DOWNGRADE = """
DROP TRIGGER IF EXISTS payroll_input_rejection_append_only ON finance.payroll_input_rejection;
DROP TRIGGER IF EXISTS payroll_input_batch_guarded ON finance.payroll_input_batch;
DROP TRIGGER IF EXISTS payroll_input_guarded ON finance.payroll_input;
DROP FUNCTION IF EXISTS finance.guard_input_batch();
DROP FUNCTION IF EXISTS finance.guard_payroll_input();
"""


def _run_sql(sql: str) -> None:
    """Raw SQL on the migration's own transaction, so % in messages is not read as a parameter."""
    op.get_bind().connection.driver_connection.execute(sql)


def upgrade() -> None:
    enable_rls("finance.payroll_input_rejection")
    _run_sql(RULES)


def downgrade() -> None:
    _run_sql(DOWNGRADE)
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON finance.payroll_input_rejection")
    op.execute("ALTER TABLE finance.payroll_input_rejection DISABLE ROW LEVEL SECURITY")
