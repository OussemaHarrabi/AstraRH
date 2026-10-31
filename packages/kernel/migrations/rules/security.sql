-- Database-enforced trust rules. Applied by migration kernel_0002.
-- These hold even if application code has a bug.

-- Tenant scope. With no tenant set this is NULL, and row-level security returns nothing.
CREATE FUNCTION core.current_tenant() RETURNS uuid
LANGUAGE sql STABLE
AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;

-- The executor needs the core schema for the function above and a few narrow reads.
GRANT USAGE ON SCHEMA core TO astra_executor;
GRANT EXECUTE ON FUNCTION core.current_tenant() TO astra_api, astra_worker, astra_executor;

-- Global catalogues: readable by all, writable only by migrations.
REVOKE ALL ON core.tenant FROM astra_api, astra_worker, astra_executor;
GRANT SELECT ON core.tenant TO astra_api, astra_worker, astra_executor;
REVOKE ALL ON trust.action_type, trust.policy_version FROM astra_api, astra_worker, astra_executor;
GRANT SELECT ON trust.action_type, trust.policy_version TO astra_api, astra_worker, astra_executor;

-- What the executor may touch outside the trust schema.
GRANT SELECT ON core.role_assignment TO astra_executor;
GRANT INSERT ON core.event_outbox TO astra_executor;

-- People records are written by the API and the worker; login attempts only by the API.
REVOKE ALL ON core.login_attempt FROM astra_worker;

-- Only people, through the API, can approve. The worker and executor can never insert one.
REVOKE ALL ON trust.approval FROM astra_api, astra_worker, astra_executor;
GRANT SELECT, INSERT ON trust.approval TO astra_api;
GRANT UPDATE (status) ON trust.approval TO astra_api;
GRANT SELECT ON trust.approval TO astra_worker;
GRANT SELECT ON trust.approval TO astra_executor;
GRANT UPDATE (status) ON trust.approval TO astra_worker, astra_executor;

-- Only the processes that execute can record an execution.
REVOKE ALL ON trust.execution FROM astra_api, astra_worker, astra_executor;
GRANT SELECT ON trust.execution TO astra_api;
GRANT SELECT, INSERT, UPDATE ON trust.execution TO astra_worker, astra_executor;

-- Proposals are never deleted.
REVOKE ALL ON trust.proposal FROM astra_api, astra_worker, astra_executor;
GRANT SELECT, UPDATE ON trust.proposal TO astra_api;
GRANT SELECT, INSERT, UPDATE ON trust.proposal TO astra_worker;
GRANT SELECT, UPDATE ON trust.proposal TO astra_executor;

-- Audit is insert and read only.
REVOKE ALL ON trust.audit_event FROM astra_api, astra_worker, astra_executor;
GRANT SELECT, INSERT ON trust.audit_event TO astra_api, astra_worker, astra_executor;

-- Decision records are immutable, and hold CV quotes the executor must not read.
REVOKE ALL ON trust.decision_record, trust.decision_factor, trust.decision_evidence,
    trust.decision_counterfactual FROM astra_api, astra_worker, astra_executor;
GRANT SELECT, INSERT ON trust.decision_record, trust.decision_factor, trust.decision_evidence,
    trust.decision_counterfactual TO astra_api, astra_worker;

-- Triggers forbid changing history, for every role including the owner.
CREATE FUNCTION trust.forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'integrity_constraint_violation';
END $$;

CREATE TRIGGER audit_event_immutable BEFORE UPDATE OR DELETE ON trust.audit_event
  FOR EACH ROW EXECUTE FUNCTION trust.forbid_change();
CREATE TRIGGER decision_record_immutable BEFORE UPDATE OR DELETE ON trust.decision_record
  FOR EACH ROW EXECUTE FUNCTION trust.forbid_change();
CREATE TRIGGER decision_factor_immutable BEFORE UPDATE OR DELETE ON trust.decision_factor
  FOR EACH ROW EXECUTE FUNCTION trust.forbid_change();
CREATE TRIGGER decision_evidence_immutable BEFORE UPDATE OR DELETE ON trust.decision_evidence
  FOR EACH ROW EXECUTE FUNCTION trust.forbid_change();
CREATE TRIGGER decision_counterfactual_immutable BEFORE UPDATE OR DELETE ON trust.decision_counterfactual
  FOR EACH ROW EXECUTE FUNCTION trust.forbid_change();

-- An approval must match the proposal's current payload, even if application code has a bug.
CREATE FUNCTION trust.check_approval_hash() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE current_hash text;
BEGIN
  SELECT payload_hash INTO current_hash FROM trust.proposal WHERE id = NEW.proposal_id;
  IF current_hash IS DISTINCT FROM NEW.payload_hash THEN
    RAISE EXCEPTION 'approval hash does not match proposal' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER approval_hash_matches BEFORE INSERT ON trust.approval
  FOR EACH ROW EXECUTE FUNCTION trust.check_approval_hash();

-- Agent checkpoints hold working state, so only the worker can reach them.
CREATE SCHEMA agent_ckpt AUTHORIZATION astra_owner;
GRANT USAGE, CREATE ON SCHEMA agent_ckpt TO astra_worker;

-- Durable jobs. The Procrastinate schema is created here by the migration.
CREATE SCHEMA jobs AUTHORIZATION astra_owner;
