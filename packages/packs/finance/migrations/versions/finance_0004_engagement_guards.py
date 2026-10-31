"""Row-level security for hire notices, and guards on engagements and their pay.

An engagement becomes active, and its terms change afterwards, only through an approved action,
which the worker applies. The API role can draft and validate but cannot skip that step.

Revision ID: finance_0004
Revises: d99850d16682
"""

from alembic import op

from kernel.rls import enable_rls

revision = "finance_0004"
down_revision = "d99850d16682"
branch_labels = None
depends_on = None

RULES = """
-- Engagements. A new one is a draft. Before activation the status moves between the validation
-- states freely. Activation, and any change once active, need the worker or the owner role.
CREATE FUNCTION finance.guard_engagement() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'draft' AND current_user <> 'astra_owner' THEN
      RAISE EXCEPTION 'A new engagement must be a draft';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Only a draft engagement can be deleted, not a % one', OLD.status;
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status IN ('active', 'completed', 'terminated')
     AND current_user NOT IN ('astra_worker', 'astra_owner') THEN
    RAISE EXCEPTION 'An % engagement changes only through an approved action', OLD.status;
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    IF (OLD.status, NEW.status) NOT IN (
         ('draft', 'pending_review'), ('draft', 'approved'),
         ('pending_review', 'draft'), ('pending_review', 'approved'),
         ('approved', 'draft'), ('approved', 'pending_review'), ('approved', 'active'),
         ('active', 'completed'), ('active', 'terminated')) THEN
      RAISE EXCEPTION 'An engagement cannot go from % to %', OLD.status, NEW.status;
    END IF;
    IF NEW.status IN ('active', 'completed', 'terminated')
       AND current_user NOT IN ('astra_worker', 'astra_owner') THEN
      RAISE EXCEPTION 'Only an approved action can make an engagement %', NEW.status;
    END IF;
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER engagement_guarded
  BEFORE INSERT OR UPDATE OR DELETE ON finance.engagement
  FOR EACH ROW EXECUTE FUNCTION finance.guard_engagement();

-- Pay of an engagement that is active or finished changes only through an approved amendment.
CREATE FUNCTION finance.guard_pay_item() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_status text; new_status text;
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    SELECT status INTO old_status FROM finance.engagement WHERE id = OLD.engagement_id;
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') THEN
    SELECT status INTO new_status FROM finance.engagement WHERE id = NEW.engagement_id;
  END IF;
  IF (old_status IN ('active', 'completed', 'terminated')
      OR new_status IN ('active', 'completed', 'terminated'))
     AND current_user NOT IN ('astra_worker', 'astra_owner') THEN
    RAISE EXCEPTION 'Pay of an active engagement changes only through an approved action';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;
CREATE TRIGGER pay_item_guarded
  BEFORE INSERT OR UPDATE OR DELETE ON finance.pay_item
  FOR EACH ROW EXECUTE FUNCTION finance.guard_pay_item();
"""

DOWNGRADE = """
DROP TRIGGER IF EXISTS pay_item_guarded ON finance.pay_item;
DROP TRIGGER IF EXISTS engagement_guarded ON finance.engagement;
DROP FUNCTION IF EXISTS finance.guard_pay_item();
DROP FUNCTION IF EXISTS finance.guard_engagement();
"""


def _run_sql(sql: str) -> None:
    """Raw SQL on the migration's own transaction, so % in messages is not read as a parameter."""
    op.get_bind().connection.driver_connection.execute(sql)


def upgrade() -> None:
    enable_rls("finance.hire_notice")
    _run_sql(RULES)


def downgrade() -> None:
    _run_sql(DOWNGRADE)
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON finance.hire_notice")
    op.execute("ALTER TABLE finance.hire_notice DISABLE ROW LEVEL SECURITY")
