"""Row-level security for payment destinations, and guards on payment lines and batches.

A payment line keeps its amount, destination and key for ever, and its status follows the only paths
the bank can report. A batch keeps what was sent. Neither is ever deleted. These hold for every
role, the owner included.

Revision ID: finance_0007
Revises: ac048a31a8b4
"""

from alembic import op

from kernel.rls import enable_rls

revision = "finance_0007"
down_revision = "ac048a31a8b4"
branch_labels = None
depends_on = None

FUNCTIONS = """
CREATE OR REPLACE FUNCTION finance.guard_payment_line() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A payment line is never deleted';
  END IF;
  IF (NEW.run_id, NEW.payslip_id, NEW.amount, NEW.idempotency_key)
     IS DISTINCT FROM
     (OLD.run_id, OLD.payslip_id, OLD.amount, OLD.idempotency_key) THEN
    RAISE EXCEPTION 'The amount and key of a payment line cannot be changed';
  END IF;
  IF NEW.bank_ref_token IS DISTINCT FROM OLD.bank_ref_token
     AND OLD.status NOT IN ('due', 'failed', 'reversed') THEN
    RAISE EXCEPTION 'The destination of a payment that was sent cannot be changed';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status
     AND (OLD.status, NEW.status) NOT IN (
       ('due', 'submitted'), ('submitted', 'paid'), ('submitted', 'part_paid'),
       ('submitted', 'failed'), ('submitted', 'reversed'), ('paid', 'reversed'),
       ('part_paid', 'paid'),
       ('failed', 'submitted'), ('reversed', 'submitted')) THEN
    RAISE EXCEPTION 'A payment cannot go from % to %', OLD.status, NEW.status;
  END IF;
  RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION finance.guard_payment_batch() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A payment batch is never deleted';
  END IF;
  IF (NEW.run_id, NEW.release_number, NEW.execution_id, NEW.provider_ref, NEW.total,
      NEW.line_count)
     IS DISTINCT FROM
     (OLD.run_id, OLD.release_number, OLD.execution_id, OLD.provider_ref, OLD.total,
      OLD.line_count) THEN
    RAISE EXCEPTION 'What was sent in a payment batch cannot be changed';
  END IF;
  RETURN NEW;
END
$$;

-- A payment reversed after the run counted as paid reopens the run.
CREATE OR REPLACE FUNCTION finance.protect_run() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'draft' AND current_user <> 'astra_owner' THEN
      RAISE EXCEPTION 'A new run must be a draft';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Only a draft run can be deleted, not a % run', OLD.status;
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status = 'closed' THEN
    RAISE EXCEPTION 'A closed run cannot be changed';
  END IF;
  IF current_user NOT IN ('astra_worker', 'astra_owner')
     AND (NEW.results_hash, NEW.inputs_hash, NEW.rule_set_refs, NEW.calculated_at,
          NEW.approved_by, NEW.approved_at, NEW.calculation_error, NEW.period_start,
          NEW.period_end, NEW.pay_date, NEW.regime_id, NEW.input_batch_refs, NEW.prepared_by)
         IS DISTINCT FROM
         (OLD.results_hash, OLD.inputs_hash, OLD.rule_set_refs, OLD.calculated_at,
          OLD.approved_by, OLD.approved_at, OLD.calculation_error, OLD.period_start,
          OLD.period_end, OLD.pay_date, OLD.regime_id, OLD.input_batch_refs, OLD.prepared_by) THEN
    RAISE EXCEPTION 'Only the worker can change the results or the identity of a run';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    IF (OLD.status, NEW.status) NOT IN (
         ('draft', 'calculated'), ('calculated', 'draft'), ('calculated', 'approval_pending'),
         ('approval_pending', 'draft'), ('approval_pending', 'approved'),
         ('approved', 'payment_pending'), ('payment_pending', 'paid'),
         ('paid', 'payment_pending'), ('paid', 'closed')) THEN
      RAISE EXCEPTION 'A run cannot go from % to %', OLD.status, NEW.status;
    END IF;
    IF NEW.status IN ('calculated', 'approved', 'payment_pending', 'paid', 'closed')
       AND current_user NOT IN ('astra_worker', 'astra_owner') THEN
      RAISE EXCEPTION 'Only the worker can move a run to %', NEW.status;
    END IF;
  END IF;
  RETURN NEW;
END
$$;
"""

TRIGGERS = """
CREATE TRIGGER payment_line_guarded
  BEFORE UPDATE OR DELETE ON finance.payment_line
  FOR EACH ROW EXECUTE FUNCTION finance.guard_payment_line();
CREATE TRIGGER payment_batch_guarded
  BEFORE UPDATE OR DELETE ON finance.payment_batch
  FOR EACH ROW EXECUTE FUNCTION finance.guard_payment_batch();
"""

DOWNGRADE = """
DROP TRIGGER IF EXISTS payment_batch_guarded ON finance.payment_batch;
DROP TRIGGER IF EXISTS payment_line_guarded ON finance.payment_line;
DROP FUNCTION IF EXISTS finance.guard_payment_batch();
DROP FUNCTION IF EXISTS finance.guard_payment_line();
"""


def _run_sql(sql: str) -> None:
    """Raw SQL on the migration's own transaction, so % in messages is not read as a parameter."""
    op.get_bind().connection.driver_connection.execute(sql)


def upgrade() -> None:
    enable_rls("finance.payment_destination")
    _run_sql(FUNCTIONS)
    _run_sql(TRIGGERS)


def downgrade() -> None:
    """Removes the payment guards. The run guard keeps the reopening transition."""
    _run_sql(DOWNGRADE)
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON finance.payment_destination")
    op.execute("ALTER TABLE finance.payment_destination DISABLE ROW LEVEL SECURITY")
