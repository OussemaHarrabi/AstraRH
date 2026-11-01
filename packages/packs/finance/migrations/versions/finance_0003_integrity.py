"""Stricter database rules for rule sets, frozen payroll and run status changes.

Closes audit findings A1, A2 and A3 (docs/FINANCE_AUDIT.md): the API could insert an active
rule set, an active rule set could be edited, and a submitted run could be changed by inserting
rows, moving rows between runs, or sending the run back to draft.

Revision ID: finance_0003
Revises: finance_0002
"""

from alembic import op

revision = "finance_0003"
down_revision = "finance_0002"
branch_labels = None
depends_on = None

RULES = """
-- Rule sets. Only the owner role (migrations and seed) may insert anything but a draft.
-- Once active, a rule set's content never changes, for any role. Status moves forward only.
CREATE FUNCTION finance.guard_rule_set() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF current_user <> 'astra_owner'
       AND (NEW.status <> 'draft' OR NEW.approved_by IS NOT NULL OR NEW.approved_at IS NOT NULL) THEN
      RAISE EXCEPTION 'A new rule set must be a draft';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Only a draft rule set can be deleted, not a % one', OLD.status;
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status <> 'draft'
     AND (NEW.definition, NEW.definition_hash, NEW.rule_id, NEW.version, NEW.jurisdiction,
          NEW.valid_from, NEW.valid_to, NEW.is_demo, NEW.source_ref, NEW.kind)
         IS DISTINCT FROM
         (OLD.definition, OLD.definition_hash, OLD.rule_id, OLD.version, OLD.jurisdiction,
          OLD.valid_from, OLD.valid_to, OLD.is_demo, OLD.source_ref, OLD.kind) THEN
    RAISE EXCEPTION 'The content of a % rule set cannot be changed', OLD.status;
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status
     AND (OLD.status, NEW.status) NOT IN (('draft', 'active'), ('active', 'superseded')) THEN
    RAISE EXCEPTION 'A rule set cannot go from % to %', OLD.status, NEW.status;
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER rule_set_guarded
  BEFORE INSERT OR UPDATE OR DELETE ON finance.rule_set
  FOR EACH ROW EXECUTE FUNCTION finance.guard_rule_set();

-- The status of the run a payslip belongs to, or NULL.
CREATE FUNCTION finance.run_status_of_payslip(payslip uuid) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT r.status FROM finance.payslip p JOIN finance.payroll_run r ON r.id = p.run_id
   WHERE p.id = payslip
$$;

-- Lines: no insert, update, delete or move into or out of a submitted run.
DROP TRIGGER payslip_line_frozen ON finance.payslip_line;
DROP FUNCTION finance.freeze_submitted_lines();
CREATE FUNCTION finance.freeze_submitted_lines() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE run_status text;
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    run_status := finance.run_status_of_payslip(OLD.payslip_id);
    IF run_status IN __FROZEN__ THEN
      RAISE EXCEPTION 'Payslip lines of a % run cannot be changed', run_status;
    END IF;
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') THEN
    run_status := finance.run_status_of_payslip(NEW.payslip_id);
    IF run_status IN __FROZEN__ THEN
      RAISE EXCEPTION 'Payslip lines of a % run cannot be changed', run_status;
    END IF;
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;
CREATE TRIGGER payslip_line_frozen
  BEFORE INSERT OR UPDATE OR DELETE ON finance.payslip_line
  FOR EACH ROW EXECUTE FUNCTION finance.freeze_submitted_lines();

-- Payslips: no insert into a submitted run, no figure change, and never moved to another run,
-- employee or engagement once either run involved is submitted.
DROP TRIGGER payslip_frozen ON finance.payslip;
DROP FUNCTION finance.freeze_submitted_payslip();
CREATE FUNCTION finance.freeze_submitted_payslip() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_status text; new_status text;
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    SELECT status INTO old_status FROM finance.payroll_run WHERE id = OLD.run_id;
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') THEN
    SELECT status INTO new_status FROM finance.payroll_run WHERE id = NEW.run_id;
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF new_status IN __FROZEN__ THEN
      RAISE EXCEPTION 'A payslip cannot be added to a % run', new_status;
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    IF old_status IN __FROZEN__ THEN
      RAISE EXCEPTION 'A payslip of a % run cannot be deleted', old_status;
    END IF;
    RETURN OLD;
  END IF;
  IF (old_status IN __FROZEN__ OR new_status IN __FROZEN__)
     AND (NEW.run_id, NEW.employee_id, NEW.engagement_id)
         IS DISTINCT FROM (OLD.run_id, OLD.employee_id, OLD.engagement_id) THEN
    RAISE EXCEPTION 'A payslip of a submitted run cannot be moved';
  END IF;
  IF old_status IN __FROZEN__
     AND (NEW.gross, NEW.employee_deductions, NEW.income_tax, NEW.solidarity, NEW.net_pay,
          NEW.employer_cost, NEW.inputs, NEW.decision_record_id)
         IS DISTINCT FROM
         (OLD.gross, OLD.employee_deductions, OLD.income_tax, OLD.solidarity, OLD.net_pay,
          OLD.employer_cost, OLD.inputs, OLD.decision_record_id) THEN
    RAISE EXCEPTION 'Figures of a % run cannot be changed', old_status;
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER payslip_frozen
  BEFORE INSERT OR UPDATE OR DELETE ON finance.payslip
  FOR EACH ROW EXECUTE FUNCTION finance.freeze_submitted_payslip();

-- Runs: a new run starts as a draft, status follows the allowed path, and the steps that only an
-- approved action may take are reserved to the worker (which applies approved actions).
DROP TRIGGER payroll_run_protected ON finance.payroll_run;
DROP FUNCTION finance.protect_run();
CREATE FUNCTION finance.protect_run() RETURNS trigger
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
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    IF (OLD.status, NEW.status) NOT IN (
         ('draft', 'calculated'), ('calculated', 'draft'), ('calculated', 'approval_pending'),
         ('approval_pending', 'draft'), ('approval_pending', 'approved'),
         ('approved', 'payment_pending'), ('payment_pending', 'paid'), ('paid', 'closed')) THEN
      RAISE EXCEPTION 'A run cannot go from % to %', OLD.status, NEW.status;
    END IF;
    IF NEW.status IN ('approved', 'payment_pending', 'paid', 'closed')
       AND current_user NOT IN ('astra_worker', 'astra_owner') THEN
      RAISE EXCEPTION 'Only an approved action can move a run to %', NEW.status;
    END IF;
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER payroll_run_protected
  BEFORE INSERT OR UPDATE OR DELETE ON finance.payroll_run
  FOR EACH ROW EXECUTE FUNCTION finance.protect_run();
"""

FROZEN = "('approval_pending', 'approved', 'payment_pending', 'paid', 'closed')"

DOWNGRADE = """
DROP TRIGGER IF EXISTS rule_set_guarded ON finance.rule_set;
DROP FUNCTION IF EXISTS finance.guard_rule_set();
"""


def _run_sql(sql: str) -> None:
    """Raw SQL on the migration's own transaction, so % in messages is not read as a parameter."""
    op.get_bind().connection.driver_connection.execute(sql)


def upgrade() -> None:
    _run_sql(RULES.replace("__FROZEN__", FROZEN))


def downgrade() -> None:
    """Removes the rule-set guard only. The stricter payslip and run triggers stay in place."""
    _run_sql(DOWNGRADE)
