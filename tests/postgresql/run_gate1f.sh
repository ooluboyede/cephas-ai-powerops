#!/usr/bin/env bash
set -Eeuo pipefail

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=postgres}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"
: "${POWEROPS_TEST_PASSWORD:=Gate1E-Disposable-Only-ChangeMe}"

admin() {
  PGPASSWORD="$PGPASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"
}
as_role() {
  local role="$1"; shift
  PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$role" -d "$PGDATABASE" "$@"
}
expect_scope_denial() {
  local role="$1" sql="$2"
  if as_role "$role" -c "$sql" >/tmp/powerops-gate1f.out 2>&1; then
    echo "FAIL: $role unexpectedly succeeded: $sql" >&2
    cat /tmp/powerops-gate1f.out >&2
    exit 1
  fi
  if ! grep -Eq 'permission denied|row-level security policy|authenticated database identity' /tmp/powerops-gate1f.out; then
    echo "FAIL: $role failed for an unexpected reason: $sql" >&2
    cat /tmp/powerops-gate1f.out >&2
    exit 1
  fi
}

echo "[Gate 1F] Positive tenant and BU writes"
as_role pwr_gate1e_bu_a1 <<'SQL'
INSERT INTO powerops_data.feeders
(tenant_id,business_unit_id,feeder_id,feeder_code,display_name,
 nominal_voltage_kv,rated_capacity_mw,source_classification,source_system,observed_at)
VALUES
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a1000000-0000-4000-8000-000000000001',
 'fa000000-0000-4000-8000-0000000000f1','A1-G1F','Gate 1F same-scope insert',
 11,5,'SYNTHETIC_NOT_CUSTOMER_DATA','gate1f-fixture',now());
UPDATE powerops_data.feeders
   SET display_name='Gate 1F same-scope update'
 WHERE feeder_id='fa000000-0000-4000-8000-0000000000f1';
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM powerops_data.feeders
     WHERE feeder_id='fa000000-0000-4000-8000-0000000000f1'
       AND display_name='Gate 1F same-scope update'
  ) THEN RAISE EXCEPTION 'same-scope write verification failed'; END IF;
END $$;
SQL

as_role pwr_gate1e_tenant_a <<'SQL'
INSERT INTO powerops_data.feeders
(tenant_id,business_unit_id,feeder_id,feeder_code,display_name,
 nominal_voltage_kv,rated_capacity_mw,source_classification,source_system,observed_at)
VALUES
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a2000000-0000-4000-8000-000000000002',
 'fa000000-0000-4000-8000-0000000000f2','A2-G1F','Tenant-scoped write to BU A2',
 11,5,'SYNTHETIC_NOT_CUSTOMER_DATA','gate1f-fixture',now());
SQL

echo "[Gate 1F] Cross-tenant INSERT and UPDATE denial"
expect_scope_denial pwr_gate1e_bu_a1 "INSERT INTO powerops_data.feeders (tenant_id,business_unit_id,feeder_id,feeder_code,display_name,nominal_voltage_kv,rated_capacity_mw,source_classification,source_system,observed_at) VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','b1000000-0000-4000-8000-000000000001','fb000000-0000-4000-8000-0000000000f1','B1-ATTACK','cross tenant',11,5,'SYNTHETIC_NOT_CUSTOMER_DATA','gate1f-attack',now())"
expect_scope_denial pwr_gate1e_bu_a1 "UPDATE powerops_data.feeders SET tenant_id='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', business_unit_id='b1000000-0000-4000-8000-000000000001' WHERE feeder_id='fa000000-0000-4000-8000-000000000001'"

echo "[Gate 1F] Runtime effective privilege and membership closure"
admin <<'SQL'
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT rolname, oid FROM pg_catalog.pg_roles WHERE rolname LIKE 'pwr_gate1e_%'
  LOOP
    -- A runtime login must never be a member of another role. PostgreSQL
    -- 16+ has one unavoidable reverse-direction bootstrap grant: the
    -- CREATEROLE provisioner is an ADMIN member of the created runtime role.
    -- It is safe only when neither SET nor INHERIT is enabled.
    IF EXISTS (
      SELECT 1
        FROM pg_catalog.pg_auth_members m
        JOIN pg_catalog.pg_roles member_role ON member_role.oid = m.member
        JOIN pg_catalog.pg_roles grantor ON grantor.oid = m.grantor
       WHERE m.member = r.oid
          OR (
            m.roleid = r.oid
            AND (
              current_setting('server_version_num')::integer < 160000
              OR member_role.rolname <> 'powerops_provisioner'
              OR NOT m.admin_option
              OR NOT grantor.rolsuper
              OR COALESCE((to_jsonb(m)->>'inherit_option')::boolean, true)
              OR COALESCE((to_jsonb(m)->>'set_option')::boolean, true)
            )
          )
    ) THEN
      RAISE EXCEPTION 'runtime role has an unsafe role membership: %', r.rolname;
    END IF;
    IF NOT has_schema_privilege(r.rolname,'powerops_data','USAGE')
       OR has_schema_privilege(r.rolname,'powerops_data','CREATE') THEN
      RAISE EXCEPTION 'unsafe operational schema privileges: %', r.rolname;
    END IF;
    IF NOT has_table_privilege(r.rolname,'powerops_data.feeders','SELECT')
       OR NOT has_table_privilege(r.rolname,'powerops_data.feeders','INSERT')
       OR NOT has_table_privilege(r.rolname,'powerops_data.feeders','UPDATE')
       OR has_table_privilege(r.rolname,'powerops_data.feeders','DELETE')
       OR has_table_privilege(r.rolname,'powerops_data.feeders','TRUNCATE')
       OR has_table_privilege(r.rolname,'powerops_data.feeders','REFERENCES')
       OR has_table_privilege(r.rolname,'powerops_data.feeders','TRIGGER') THEN
      RAISE EXCEPTION 'unsafe effective table privileges: %', r.rolname;
    END IF;
    IF has_function_privilege(r.rolname,
       'powerops_security.provision_scope_login(name,uuid,text,uuid)','EXECUTE')
       OR has_function_privilege(r.rolname,
       'powerops_security.retire_scope_login(name,text)','EXECUTE') THEN
      RAISE EXCEPTION 'runtime role can invoke privileged lifecycle function: %', r.rolname;
    END IF;
  END LOOP;
  IF (SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname LIKE 'pwr_gate1e_%') <> 4 THEN
    RAISE EXCEPTION 'expected exactly four Gate 1E runtime roles';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='powerops_data' AND c.relkind='r'
      AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity)
  ) THEN RAISE EXCEPTION 'operational table missing ENABLE/FORCE RLS'; END IF;
END $$;
SQL

echo "[Gate 1F] SET ROLE escalation denial"
if as_role pwr_gate1e_bu_a1 -c 'SET ROLE pwr_gate1e_tenant_a' >/tmp/powerops-gate1f.out 2>&1; then
  echo "FAIL: runtime identity switched to another scope role" >&2
  exit 1
fi
grep -q 'permission denied' /tmp/powerops-gate1f.out || { cat /tmp/powerops-gate1f.out >&2; exit 1; }

echo "[Gate 1F] Unmapped and inactive identities fail closed"
admin <<'SQL'
CREATE ROLE pwr_gate1f_unmapped NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA powerops_security TO pwr_gate1f_unmapped;
GRANT EXECUTE ON FUNCTION powerops_security.resolve_authenticated_scope() TO pwr_gate1f_unmapped;
ALTER ROLE pwr_gate1f_unmapped LOGIN PASSWORD 'Gate1E-Disposable-Only-ChangeMe';

SELECT powerops_security.provision_scope_login(
 'pwr_gate1f_inactive','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','business_unit',
 'a1000000-0000-4000-8000-000000000001');
ALTER ROLE pwr_gate1f_inactive PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
UPDATE powerops_security.role_scope_binding
   SET active=false
 WHERE role_name='pwr_gate1f_inactive';
SQL
expect_scope_denial pwr_gate1f_unmapped "SELECT * FROM powerops_security.resolve_authenticated_scope()"
expect_scope_denial pwr_gate1f_inactive "SELECT * FROM powerops_security.resolve_authenticated_scope()"

echo "[Gate 1F] Retired identity tombstone denies resolver even if stale binding is active"
admin <<'SQL'
SELECT powerops_security.provision_scope_login(
 'pwr_gate1f_retired','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','business_unit',
 'a1000000-0000-4000-8000-000000000001');
ALTER ROLE pwr_gate1f_retired PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
INSERT INTO powerops_security.retired_role_identity
(cluster_id,role_oid,role_name,retirement_reason)
SELECT cluster_id,role_oid,role_name,'Gate 1F resolver tombstone adversarial test'
FROM powerops_security.role_scope_binding
WHERE role_name='pwr_gate1f_retired';
SQL
expect_scope_denial pwr_gate1f_retired "SELECT * FROM powerops_security.resolve_authenticated_scope()"

echo "[Gate 1F] Invalid provisioning tuple must roll back without creating a role"
admin <<'SQL'
DO $$
BEGIN
  BEGIN
    PERFORM powerops_security.provision_scope_login(
      'pwr_gate1f_invalid','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','business_unit',NULL);
    RAISE EXCEPTION 'invalid provisioning unexpectedly succeeded';
  EXCEPTION WHEN invalid_parameter_value THEN
    NULL;
  END;
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='pwr_gate1f_invalid') THEN
    RAISE EXCEPTION 'failed provisioning left a database role behind';
  END IF;
END $$;
SQL

echo "[Gate 1F] PASS — adversarial assertions executed; this is not an independent review or production certification"
