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
        text, text, uuid, text, integer, boolean, boolean, boolean, jsonb, text
    ) TO pwr_revocation_audit_test;

DO $$
BEGIN
    IF NOT has_function_privilege(
        'pwr_revocation_audit_test',
        'powerops_security.record_human_session_revocation_audit(text,text,uuid,text,integer,boolean,boolean,boolean,jsonb,text)',
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
    ) OR has_table_privilege(
        'pwr_revocation_audit_test',
        'powerops_security.human_session_revocation_audit',
        'TRUNCATE'
    ) THEN
        RAISE EXCEPTION 'audit writer must not have direct table DML';
    END IF;
END
$$;
SQL

# PS-02.1A.5 creates and then fences this exact fixture session, and
# verifies that its registered backend count is zero before this harness runs.
SESSION_ID='a1400000-0000-4000-8000-000000000002'

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
    true,
    jsonb_build_object('session_id', :'session_id'::text),
    'integration-test-receipt-signature'
);
SQL

AUDIT_ROWS="$(psql "$POWEROPS_TEST_ADMIN_DATABASE_URL" -X -v ON_ERROR_STOP=1 -At \
  -c "SELECT count(*) FROM powerops_security.human_session_revocation_audit WHERE session_id = '$SESSION_ID'::uuid AND event_type = 'human_database_session_revoked' AND outcome = 'verified' AND credential_revoked AND admission_fenced AND backend_termination_verified")"
if [[ "$AUDIT_ROWS" != "1" ]]; then
  echo "Expected exactly one verified append-only audit row; got: $AUDIT_ROWS" >&2
  exit 1
fi

# A writer must not be able to fabricate a verified event for a UUID with no
# protected session binding, even when it supplies every boolean as true.
if PGPASSWORD=Gate1E-Disposable-Only-ChangeMe psql \
  "host=${PGHOST:-127.0.0.1} port=${PGPORT:-5432} dbname=${PGDATABASE:-postgres} user=pwr_revocation_audit_test" \
  -X -v ON_ERROR_STOP=1 <<'SQL'
SELECT powerops_security.record_human_session_revocation_audit(
    'human_database_session_revoked',
    'oidc|integration-test-subject',
    'ffffffff-ffff-4fff-8fff-ffffffffffff'::uuid,
    'verified', 0, true, true, true,
    jsonb_build_object(
        'session_id', 'ffffffff-ffff-4fff-8fff-ffffffffffff'
    ),
    'integration-test-receipt-signature'
);
SQL
then
  echo "FAIL: audit writer fabricated verified containment for a nonexistent session" >&2
  exit 1
fi

# Direct TRUNCATE is denied independently of INSERT/UPDATE/DELETE.
if PGPASSWORD=Gate1E-Disposable-Only-ChangeMe psql \
  "host=${PGHOST:-127.0.0.1} port=${PGPORT:-5432} dbname=${PGDATABASE:-postgres} user=pwr_revocation_audit_test" \
  -X -v ON_ERROR_STOP=1 \
  -c "TRUNCATE powerops_security.human_session_revocation_audit"
then
  echo "FAIL: audit writer unexpectedly truncated the audit table" >&2
  exit 1
fi

echo "PS-02.1A.7 audit migration and least-privilege integration checks completed."
