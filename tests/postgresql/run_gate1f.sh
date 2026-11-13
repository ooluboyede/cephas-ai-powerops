#!/usr/bin/env bash
set -Eeuo pipefail

# Gate 1F layers additional adversarial assertions over the disposable Gate 1E
# fixture. It never runs against a customer database.
bash tests/postgresql/run_gate1e.sh

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=postgres}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"
: "${POWEROPS_TEST_PASSWORD:=Gate1E-Disposable-Only-ChangeMe}"

psql_admin() {
  PGPASSWORD="$PGPASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"
}
psql_role() {
  local role="$1"; shift
  PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$role" -d "$PGDATABASE" "$@"
}

echo "[Gate 1F] Positive same-scope BU writes"
psql_role pwr_gate1e_bu_a1 <<'SQL'
INSERT INTO powerops_data.feeders
(tenant_id,business_unit_id,feeder_id,feeder_code,display_name,
 nominal_voltage_kv,rated_capacity_mw,source_classification,source_system,observed_at)
VALUES
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a1000000-0000-4000-8000-000000000001',
 'fa000000-0000-4000-8000-000000000010','A1-POSITIVE','Positive same-scope write',
 11,5,'SYNTHETIC_NOT_CUSTOMER_DATA','gate1f-positive',now());
UPDATE powerops_data.feeders
   SET display_name='Positive same-scope update'
 WHERE feeder_id='fa000000-0000-4000-8000-000000000010';
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM powerops_data.feeders
     WHERE feeder_id='fa000000-0000-4000-8000-000000000010'
       AND display_name='Positive same-scope update'
  ) THEN
    RAISE EXCEPTION 'same-scope INSERT/UPDATE did not persist';
  END IF;
END
$$;
SQL

echo "[Gate 1F] Cross-tenant insert and scope-changing update must fail"
psql_role pwr_gate1e_tenant_a <<'SQL'
DO $$
BEGIN
  BEGIN
    INSERT INTO powerops_data.feeders
    (tenant_id,business_unit_id,feeder_id,feeder_code,display_name,
     nominal_voltage_kv,rated_capacity_mw,source_classification,source_system,observed_at)
    VALUES
    ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','b1000000-0000-4000-8000-000000000001',
     'fb000000-0000-4000-8000-000000000099','B1-ATTACK','Cross-tenant attempt',
     11,5,'SYNTHETIC_NOT_CUSTOMER_DATA','gate1f-attack',now());
    RAISE EXCEPTION 'cross-tenant INSERT unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;

  BEGIN
    UPDATE powerops_data.feeders
       SET tenant_id='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
           business_unit_id='b1000000-0000-4000-8000-000000000001'
     WHERE feeder_id='fa000000-0000-4000-8000-000000000001';
    RAISE EXCEPTION 'cross-tenant scope-changing UPDATE unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
END
$$;
SQL

echo "[Gate 1F] Verify role membership and effective privilege boundaries"
psql_admin <<'SQL'
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT oid, rolname FROM pg_catalog.pg_roles
     WHERE rolname LIKE 'pwr_gate1e_%'
  LOOP
    IF EXISTS (
      SELECT 1 FROM pg_catalog.pg_auth_members m
       WHERE m.member = r.oid OR m.roleid = r.oid
    ) THEN
      RAISE EXCEPTION 'runtime role has direct membership edge: %', r.rolname;
    END IF;
    IF has_table_privilege(r.rolname, 'powerops_data.feeders', 'DELETE')
       OR has_table_privilege(r.rolname, 'powerops_data.feeders', 'TRUNCATE')
       OR has_table_privilege(r.rolname, 'powerops_data.feeders', 'REFERENCES')
       OR has_table_privilege(r.rolname, 'powerops_data.feeders', 'TRIGGER') THEN
      RAISE EXCEPTION 'runtime role has prohibited feeder privilege: %', r.rolname;
    END IF;
    IF NOT has_table_privilege(r.rolname, 'powerops_data.feeders', 'SELECT')
       OR NOT has_table_privilege(r.rolname, 'powerops_data.feeders', 'INSERT')
       OR NOT has_table_privilege(r.rolname, 'powerops_data.feeders', 'UPDATE') THEN
      RAISE EXCEPTION 'runtime role lacks expected feeder DML privilege: %', r.rolname;
    END IF;
  END LOOP;
END
$$;
SQL

echo "[Gate 1F] Resolver fails closed for an unmapped authenticated login"
psql_admin <<'SQL'
CREATE ROLE pwr_gate1f_unmapped LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA powerops_security TO pwr_gate1f_unmapped;
GRANT EXECUTE ON FUNCTION powerops_security.resolve_authenticated_scope() TO pwr_gate1f_unmapped;
ALTER ROLE pwr_gate1f_unmapped PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
SQL
psql_role pwr_gate1f_unmapped <<'SQL'
DO $$
BEGIN
  BEGIN
    PERFORM * FROM powerops_security.resolve_authenticated_scope();
    RAISE EXCEPTION 'unmapped login unexpectedly resolved a scope';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
END
$$;
SQL

echo "[Gate 1F] Resolver fails closed for a tombstoned identity"
psql_admin <<'SQL'
INSERT INTO powerops_security.retired_role_identity
(cluster_id, role_oid, role_name, retirement_reason)
SELECT ci.cluster_id, r.oid, r.rolname, 'Gate 1F tombstone fail-closed fixture'
  FROM powerops_security.cluster_identity ci
 CROSS JOIN pg_catalog.pg_roles r
 WHERE ci.singleton AND r.rolname='pwr_gate1f_unmapped';
SQL
psql_role pwr_gate1f_unmapped <<'SQL'
DO $$
BEGIN
  BEGIN
    PERFORM * FROM powerops_security.resolve_authenticated_scope();
    RAISE EXCEPTION 'tombstoned login unexpectedly resolved a scope';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
END
$$;
SQL

echo "[Gate 1F] PASS — additional disposable adversarial assertions completed"
