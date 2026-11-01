"""Row-level security, role permissions and immutability rules for finance.

Revision ID: finance_0002
Revises: 3e65e32a7d91
"""

from alembic import op

from kernel.rls import enable_rls

revision = "finance_0002"
down_revision = "3e65e32a7d91"
branch_labels = None
depends_on = None

TABLES = (
    "employer_profile",
    "engagement",
    "engagement_amendment",
    "pay_item",
    "document_ref",
    "validation_issue",
    "civp_placement",
    "civp_ledger_entry",
    "civp_training",
    "civp_extension_request",
    "rule_set",
    "payroll_input_batch",
    "payroll_input",
    "payroll_run",
    "payslip",
    "payslip_line",
    "adjustment",
    "payment_batch",
    "payment_line",
    "payment_status_event",
)

FROZEN = "('approval_pending', 'approved', 'payment_pending', 'paid', 'closed')"

RULES = """
-- Roles. The executor has no access to this schema at all: it never gets USAGE.
-- Only the worker records payslips, payments and bank statuses. The API can read them.
REVOKE ALL ON finance.payslip, finance.payslip_line FROM astra_api;
GRANT SELECT ON finance.payslip, finance.payslip_line TO astra_api;
REVOKE ALL ON finance.payment_batch, finance.payment_line FROM astra_api;
GRANT SELECT ON finance.payment_batch, finance.payment_line TO astra_api;
REVOKE ALL ON finance.payment_status_event FROM astra_api, astra_worker;
GRANT SELECT ON finance.payment_status_event TO astra_api;
GRANT SELECT, INSERT ON finance.payment_status_event TO astra_worker;
-- A rule set can be drafted through the API but only the worker can change its status.
REVOKE UPDATE, DELETE ON finance.rule_set FROM astra_api;

-- Bank statuses are history: no update, no delete, even for the owner role in application code.
CREATE FUNCTION finance.forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% on finance.% is not allowed', TG_OP, TG_TABLE_NAME;
END
$$;
CREATE TRIGGER payment_status_event_append_only
  BEFORE UPDATE OR DELETE ON finance.payment_status_event
  FOR EACH ROW EXECUTE FUNCTION finance.forbid_change();

-- Once a run is submitted, its payslips and lines are frozen. Rejecting it returns it to draft.
CREATE FUNCTION finance.freeze_submitted_lines() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE run_status text;
BEGIN
  SELECT r.status INTO run_status
    FROM finance.payslip p JOIN finance.payroll_run r ON r.id = p.run_id
   WHERE p.id = OLD.payslip_id;
  IF run_status IN __FROZEN__ THEN
    RAISE EXCEPTION 'Payslip lines of a % run cannot be changed', run_status;
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;
CREATE TRIGGER payslip_line_frozen
  BEFORE UPDATE OR DELETE ON finance.payslip_line
  FOR EACH ROW EXECUTE FUNCTION finance.freeze_submitted_lines();

CREATE FUNCTION finance.freeze_submitted_payslip() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE run_status text;
BEGIN
  SELECT status INTO run_status FROM finance.payroll_run WHERE id = OLD.run_id;
  IF run_status IN __FROZEN__ THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'A payslip of a % run cannot be deleted', run_status;
    END IF;
    IF (NEW.gross, NEW.employee_deductions, NEW.income_tax, NEW.solidarity, NEW.net_pay,
        NEW.employer_cost, NEW.inputs)
       IS DISTINCT FROM
       (OLD.gross, OLD.employee_deductions, OLD.income_tax, OLD.solidarity, OLD.net_pay,
        OLD.employer_cost, OLD.inputs) THEN
      RAISE EXCEPTION 'Figures of a % run cannot be changed', run_status;
    END IF;
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;
CREATE TRIGGER payslip_frozen
  BEFORE UPDATE OR DELETE ON finance.payslip
  FOR EACH ROW EXECUTE FUNCTION finance.freeze_submitted_payslip();

-- A closed run never changes, and only a draft run can be deleted.
CREATE FUNCTION finance.protect_run() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Only a draft run can be deleted, not a % run', OLD.status;
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status = 'closed' THEN
    RAISE EXCEPTION 'A closed run cannot be changed';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER payroll_run_protected
  BEFORE UPDATE OR DELETE ON finance.payroll_run
  FOR EACH ROW EXECUTE FUNCTION finance.protect_run();
"""

DOWNGRADE = """
DROP TRIGGER IF EXISTS payroll_run_protected ON finance.payroll_run;
DROP TRIGGER IF EXISTS payslip_frozen ON finance.payslip;
DROP TRIGGER IF EXISTS payslip_line_frozen ON finance.payslip_line;
DROP TRIGGER IF EXISTS payment_status_event_append_only ON finance.payment_status_event;
DROP FUNCTION IF EXISTS finance.protect_run();
DROP FUNCTION IF EXISTS finance.freeze_submitted_payslip();
DROP FUNCTION IF EXISTS finance.freeze_submitted_lines();
DROP FUNCTION IF EXISTS finance.forbid_change();
"""


def _run_sql(sql: str) -> None:
    """Raw SQL on the migration's own transaction, so % in messages is not read as a parameter."""
    op.get_bind().connection.driver_connection.execute(sql)


def upgrade() -> None:
    enable_rls(*(f"finance.{name}" for name in TABLES))
    _run_sql(RULES.replace("__FROZEN__", FROZEN))


def downgrade() -> None:
    _run_sql(DOWNGRADE)
    for name in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON finance.{name}")
        op.execute(f"ALTER TABLE finance.{name} DISABLE ROW LEVEL SECURITY")
