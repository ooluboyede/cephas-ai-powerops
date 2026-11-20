#!/usr/bin/env bash
set -euo pipefail

: "${POWEROPS_TEST_ADMIN_DATABASE_URL:?POWEROPS_TEST_ADMIN_DATABASE_URL is required}"

psql "$POWEROPS_TEST_ADMIN_DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f migrations/postgresql/0016_human_session_revocation_audit.sql

psql "$POWEROPS_TEST_ADMIN_DATABASE_URL" -X -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
         WHERE rolname = 'pwr_revocation_audit_test'
    ) THEN
        CREATE ROLE pwr_revocation_audit_test LOGIN
            PASSWORD 'Gate1E-Disposable-Only-ChangeMe'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
            NOREPLICATION NOBYPASSRLS;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA powerops_security TO pwr_revocation_audit_test;
GRANT EXECUTE ON FUNCTION
    powerops_security.record_human_session_revocation_audit(
        text, text, uuid, text, integer, boolean, boolean, boolean
    ) TO pwr_revocation_audit_test;

DO $$
BEGIN
    IF NOT has_function_privilege(
        'pwr_revocation_audit_test',
        'powerops_security.record_human_session_revocation_audit(text,text,uuid,text,integer,boolean,boolean,boolean)',
        'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'audit writer lacks required function execution';
    END IF;
    IF has_table_privilege(
        'pwr_revocation_audit_test',
        'powerops_security.human_session_revocation_audit',
        'INSERT'
    ) OR has_table_privilege(
        'pwr_revocation_audit_test',
        'powerops_security.human_session_revocation_audit',
        'UPDATE'
    ) OR has_table_privilege(
        'pwr_revocation_audit_test',
        'powerops_security.human_session_revocation_audit',
        'DELETE'
    ) THEN
        RAISE EXCEPTION 'audit writer must not have direct table DML';
    END IF;
END
$$;
SQL

psql "$POWEROPS_TEST_ADMIN_DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -c "SELECT set_config('powerops.test_audit_session_id', gen_random_uuid()::text, false)" \
  -tA > /tmp/powerops-audit-session-id
SESSION_ID="$(cat /tmp/powerops-audit-session-id)"

PGPASSWORD=Gate1E-Disposable-Only-ChangeMe psql \
  "host=${PGHOST:-127.0.0.1} port=${PGPORT:-5432} dbname=${PGDATABASE:-postgres} user=pwr_revocation_audit_test" \
  -X -v ON_ERROR_STOP=1 -v session_id="$SESSION_ID" <<'SQL'
SELECT powerops_security.record_human_session_revocation_audit(
    'human_database_session_revoked',
    'oidc|integration-test-subject',
    :'session_id'::uuid,
    'verified',
    0,
    true,
    true,
    true
);
SQL

psql "$POWEROPS_TEST_ADMIN_DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -v session_id="$SESSION_ID" <<'SQL'
DO $$
DECLARE
    v_count integer;
BEGIN
    SELECT count(*)::integer INTO v_count
      FROM powerops_security.human_session_revocation_audit
     WHERE session_id = :'session_id'::uuid
       AND event_type = 'human_database_session_revoked'
       AND outcome = 'verified'
       AND credential_revoked
       AND admission_fenced
       AND backend_termination_verified;
    IF v_count <> 1 THEN
        RAISE EXCEPTION 'append-only audit record was not persisted exactly once';
    END IF;
END
$$;
SQL

echo "PS-02.1A.7 audit migration and least-privilege integration checks completed."
