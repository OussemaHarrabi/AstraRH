#!/bin/bash
# Runs once, on an empty database volume. Creates per-process roles and schemas.
# No application role is a superuser or has BYPASSRLS, so row-level security applies to all of them.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username postgres --dbname astra \
  -v owner_pw="$ASTRA_OWNER_PASSWORD" \
  -v api_pw="$ASTRA_API_PASSWORD" \
  -v worker_pw="$ASTRA_WORKER_PASSWORD" \
  -v executor_pw="$ASTRA_EXECUTOR_PASSWORD" <<'SQL'
CREATE ROLE astra_owner    LOGIN PASSWORD :'owner_pw'    NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE ROLE astra_api      LOGIN PASSWORD :'api_pw'      NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE ROLE astra_worker   LOGIN PASSWORD :'worker_pw'   NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE ROLE astra_executor LOGIN PASSWORD :'executor_pw' NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE astra FROM PUBLIC;
GRANT CONNECT ON DATABASE astra TO astra_owner, astra_api, astra_worker, astra_executor;
GRANT CREATE ON DATABASE astra TO astra_owner;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
GRANT USAGE ON SCHEMA public TO astra_owner, astra_api, astra_worker;

DO $$
DECLARE s text;
BEGIN
  FOREACH s IN ARRAY ARRAY['core','trust','ai','knowledge','comms','calendar','talent','journey','finance','workforce'] LOOP
    EXECUTE format('CREATE SCHEMA %I AUTHORIZATION astra_owner', s);
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO astra_api, astra_worker', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE astra_owner IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO astra_api, astra_worker', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE astra_owner IN SCHEMA %I GRANT USAGE, SELECT ON SEQUENCES TO astra_api, astra_worker', s);
  END LOOP;
END $$;

-- The executor sees the trust ledger only: never CVs, salaries, cases or other pack data.
GRANT USAGE ON SCHEMA trust TO astra_executor;
ALTER DEFAULT PRIVILEGES FOR ROLE astra_owner IN SCHEMA trust GRANT SELECT, INSERT, UPDATE ON TABLES TO astra_executor;
ALTER DEFAULT PRIVILEGES FOR ROLE astra_owner IN SCHEMA trust GRANT USAGE, SELECT ON SEQUENCES TO astra_executor;
SQL
