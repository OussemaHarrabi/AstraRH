"""Guards for payroll runs: who may change what, and inputs locked once a run is submitted.

Calculated results, their hashes and the approval fields can be written only by the worker (which
calculates and applies approved actions) or the owner role. A run can reach `calculated` only
through the worker. The inputs a run used cannot be withdrawn once the run is submitted.

Revision ID: finance_0006
Revises: c610f6d481b6
"""

from alembic import op

from kernel.rls import enable_rls

revision = "finance_0006"
down_revision = "c610f6d481b6"
branch_labels = None
depends_on = None

FROZEN = "('approval_pending', 'approved', 'payment_pending', 'paid', 'closed')"

RULES = """
-- Only the worker writes which inputs a run used. The API can read them.
REVOKE ALL ON finance.payroll_run_input FROM astra_api;
GRANT SELECT ON finance.payroll_run_input TO astra_api;

CREATE FUNCTION finance.freeze_run_inputs() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE run_status text;
BEGIN
  SELECT status INTO run_status FROM finance.payroll_run
   WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.run_id ELSE NEW.run_id END;
  IF run_status IN __FROZEN__ THEN
    RAISE EXCEPTION 'The inputs of a % run cannot be changed', run_status;
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;
CREATE TRIGGER payroll_run_input_frozen
  BEFORE INSERT OR UPDATE OR DELETE ON finance.payroll_run_input
  FOR EACH ROW EXECUTE FUNCTION finance.freeze_run_inputs();

-- An input used by a submitted run cannot be withdrawn.
CREATE OR REPLACE FUNCTION finance.guard_payroll_input() RETURNS trigger
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
  IF NEW.status = 'withdrawn' AND OLD.status = 'accepted' AND EXISTS (
       SELECT 1 FROM finance.payroll_run_input l JOIN finance.payroll_run r ON r.id = l.run_id
        WHERE l.input_id = OLD.id AND r.status IN __FROZEN__) THEN
    RAISE EXCEPTION 'This input is used by a submitted payroll run';
  END IF;
  RETURN NEW;
END
$$;

-- Runs: the same rules as before, plus column-level limits and a worker-only way to `calculated`.
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
         ('approved', 'payment_pending'), ('payment_pending', 'paid'), ('paid', 'closed')) THEN
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

DOWNGRADE = """
DROP TRIGGER IF EXISTS payroll_run_input_frozen ON finance.payroll_run_input;
DROP FUNCTION IF EXISTS finance.freeze_run_inputs();
"""


def _run_sql(sql: str) -> None:
    """Raw SQL on the migration's own transaction, so % in messages is not read as a parameter."""
    op.get_bind().connection.driver_connection.execute(sql)


def upgrade() -> None:
    enable_rls("finance.payroll_run_input")
    _run_sql(RULES.replace("__FROZEN__", FROZEN))


def downgrade() -> None:
    """Removes the link guard only. The stricter run and input functions stay in place."""
    _run_sql(DOWNGRADE)
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON finance.payroll_run_input")
    op.execute("ALTER TABLE finance.payroll_run_input DISABLE ROW LEVEL SECURITY")
