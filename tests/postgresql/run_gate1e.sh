#!/usr/bin/env bash
set -Eeuo pipefail

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=postgres}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"
: "${POWEROPS_TEST_PASSWORD:=Gate1E-Disposable-Only-ChangeMe}"

psql_admin() {
  PGPASSWORD="$PGPASSWORD" psql -X -v ON_ERROR_STOP=1 \
    -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"
}
psql_role() {
  local role="$1"; shift
  PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql -X -v ON_ERROR_STOP=1 \
    -h "$PGHOST" -p "$PGPORT" -U "$role" -d "$PGDATABASE" "$@"
}

echo "[Gate 1E] PostgreSQL version"
psql_admin -Atc 'SHOW server_version'

echo "[Gate 1E] Apply migrations 0001–0005"
for migration in \
  migrations/postgresql/0001_bootstrap_roles.sql \
  migrations/postgresql/0002_scope_identity.sql \
  migrations/postgresql/0003_scope_login_lifecycle.sql \
  migrations/postgresql/0004_row_scope_predicate.sql \
  migrations/postgresql/0005_operational_schema_rls.sql
do
  echo "Applying $migration"
  psql_admin -f "$migration"
done

echo "[Gate 1E] Seed disposable cluster identity and synthetic fixture rows"
psql_admin <<'SQL'
INSERT INTO powerops_security.cluster_identity(singleton, cluster_id)
VALUES (true, '10000000-0000-4000-8000-000000000001');

INSERT INTO powerops_data.business_units
(tenant_id,business_unit_id,business_unit_code,display_name)
VALUES
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a1000000-0000-4000-8000-000000000001','A1','Tenant A BU 1'),
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a2000000-0000-4000-8000-000000000002','A2','Tenant A BU 2'),
('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','b1000000-0000-4000-8000-000000000001','B1','Tenant B BU 1');

INSERT INTO powerops_data.feeders
(tenant_id,business_unit_id,feeder_id,feeder_code,display_name,
 nominal_voltage_kv,rated_capacity_mw,source_classification,source_system,observed_at)
VALUES
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a1000000-0000-4000-8000-000000000001','fa000000-0000-4000-8000-000000000001','A1-F1','Synthetic A1 feeder',11,5,'SYNTHETIC_NOT_CUSTOMER_DATA','gate1e-fixture',now()),
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a2000000-0000-4000-8000-000000000002','fa000000-0000-4000-8000-000000000002','A2-F1','Synthetic A2 feeder',11,5,'SYNTHETIC_NOT_CUSTOMER_DATA','gate1e-fixture',now()),
('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','b1000000-0000-4000-8000-000000000001','fb000000-0000-4000-8000-000000000001','B1-F1','Synthetic B1 feeder',11,5,'SYNTHETIC_NOT_CUSTOMER_DATA','gate1e-fixture',now());

SELECT powerops_security.provision_scope_login(
 'pwr_gate1e_tenant_a','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','tenant',NULL);
SELECT powerops_security.provision_scope_login(
 'pwr_gate1e_bu_a1','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','business_unit',
 'a1000000-0000-4000-8000-000000000001');
SELECT powerops_security.provision_scope_login(
 'pwr_gate1e_bu_a2','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','business_unit',
 'a2000000-0000-4000-8000-000000000002');
SELECT powerops_security.provision_scope_login(
 'pwr_gate1e_tenant_b','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','tenant',NULL);

ALTER ROLE pwr_gate1e_tenant_a PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
ALTER ROLE pwr_gate1e_bu_a1 PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
ALTER ROLE pwr_gate1e_bu_a2 PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
ALTER ROLE pwr_gate1e_tenant_b PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
SQL

echo "[Gate 1E] Assert tenant and BU visibility using real login connections"
# psql variables are not interpolated inside dollar-quoted DO blocks; use a
# literal-safe SQL assertion generated from a validated numeric expected value.
assert_count() {
  local role="$1" expected="$2"
  [[ "$expected" =~ ^[0-9]+$ ]] || exit 2
  psql_role "$role" -c "DO \$\$ DECLARE n bigint; BEGIN SELECT count(*) INTO n FROM powerops_data.feeders; IF n <> $expected THEN RAISE EXCEPTION 'expected $expected visible feeders, got %', n; END IF; END \$\$;"
}
assert_count pwr_gate1e_tenant_a 2
assert_count pwr_gate1e_bu_a1 1
assert_count pwr_gate1e_bu_a2 1
assert_count pwr_gate1e_tenant_b 1

echo "[Gate 1E] Assert cross-scope insert and scope-changing update are rejected"
psql_role pwr_gate1e_bu_a1 <<'SQL'
DO $$
BEGIN
  BEGIN
    INSERT INTO powerops_data.feeders
    (tenant_id,business_unit_id,feeder_id,feeder_code,display_name,
     nominal_voltage_kv,rated_capacity_mw,source_classification,source_system,observed_at)
    VALUES
    ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a2000000-0000-4000-8000-000000000002',
     'fa000000-0000-4000-8000-000000000099','A2-ATTACK','Cross-BU attempt',
     11,5,'SYNTHETIC_NOT_CUSTOMER_DATA','gate1e-attack',now());
    RAISE EXCEPTION 'FAIL: cross-BU insert unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;

  BEGIN
    UPDATE powerops_data.feeders
       SET business_unit_id='a2000000-0000-4000-8000-000000000002'
     WHERE feeder_id='fa000000-0000-4000-8000-000000000001';
    RAISE EXCEPTION 'FAIL: scope-changing update unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
END
$$;
SQL

echo "[Gate 1E] Assert runtime roles cannot DELETE"
psql_role pwr_gate1e_bu_a1 <<'SQL'
DO $$
BEGIN
  BEGIN
    DELETE FROM powerops_data.feeders
     WHERE feeder_id='fa000000-0000-4000-8000-000000000001';
    RAISE EXCEPTION 'FAIL: runtime DELETE unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
END
$$;
SQL

echo "[Gate 1E] Inspect runtime role attributes"
psql_admin -Atc "
SELECT rolname || ':' || rolcanlogin || ':' || rolsuper || ':' ||
       rolcreatedb || ':' || rolcreaterole || ':' || rolinherit || ':' ||
       rolreplication || ':' || rolbypassrls
FROM pg_catalog.pg_roles
WHERE rolname LIKE 'pwr_gate1e_%'
ORDER BY rolname" | while IFS=: read -r role canlogin super createdb createrole inherit replication bypassrls; do
  [[ "$canlogin" == "true" && "$super" == "false" && "$createdb" == "false" &&
     "$createrole" == "false" && "$inherit" == "false" && "$replication" == "false" &&
     "$bypassrls" == "false" ]] || {
       echo "Unsafe runtime role attributes: $role" >&2
       exit 1
     }
done

echo "[Gate 1E] PASS — disposable baseline migration and RLS checks completed"
