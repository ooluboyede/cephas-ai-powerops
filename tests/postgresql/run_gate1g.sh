#!/usr/bin/env bash
set -Eeuo pipefail

# Gate 1G runs only against the disposable PostgreSQL fixture.
bash tests/postgresql/run_gate1f.sh

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=postgres}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"

psql_admin() {
  PGPASSWORD="$PGPASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"
}

echo "[Gate 1G] Provisioning validation failure leaves no role or binding"
psql_admin <<'SQL'
DO $$
DECLARE
  v_role constant name := 'pwr_gate1g_rollback';
  v_cluster uuid;
BEGIN
  SELECT cluster_id INTO STRICT v_cluster
    FROM powerops_security.cluster_identity WHERE singleton;

  BEGIN
    PERFORM powerops_security.provision_scope_login(
      v_role, NULL, 'business_unit',
      'a1000000-0000-4000-8000-000000000001'
    );
    RAISE EXCEPTION 'invalid provisioning request unexpectedly succeeded';
  EXCEPTION WHEN invalid_parameter_value THEN
    NULL;
  END;

  IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=v_role) THEN
    RAISE EXCEPTION 'failed provisioning left a PostgreSQL role behind';
  END IF;
  IF EXISTS (
    SELECT 1 FROM powerops_security.role_scope_binding
     WHERE cluster_id=v_cluster AND role_name=v_role
  ) THEN
    RAISE EXCEPTION 'failed provisioning left a scope binding behind';
  END IF;
  IF EXISTS (
    SELECT 1 FROM powerops_security.retired_role_identity
     WHERE cluster_id=v_cluster AND role_name=v_role
  ) THEN
    RAISE EXCEPTION 'failed provisioning unexpectedly created a tombstone';
  END IF;
END
$$;
SQL

echo "[Gate 1G] Reject transitive role membership paths for runtime logins"
psql_admin <<'SQL'
DO $$
DECLARE
  v_role record;
BEGIN
  FOR v_role IN
    SELECT oid, rolname FROM pg_catalog.pg_roles
     WHERE rolname LIKE 'pwr_gate1e_%'
  LOOP
    IF EXISTS (
      WITH RECURSIVE memberships(role_oid) AS (
        SELECT m.roleid
          FROM pg_catalog.pg_auth_members m
         WHERE m.member = v_role.oid
        UNION
        SELECT m.roleid
          FROM pg_catalog.pg_auth_members m
          JOIN memberships prior ON m.member = prior.role_oid
      )
      SELECT 1 FROM memberships
    ) THEN
      RAISE EXCEPTION 'runtime role has a direct or transitive membership path: %',
        v_role.rolname;
    END IF;
  END LOOP;
END
$$;
SQL

echo "[Gate 1G] Retire a scoped login and verify identity fencing"
psql_admin <<'SQL'
SELECT powerops_security.retire_scope_login(
  'pwr_gate1e_tenant_b',
  'Gate 1G disposable retirement and identity-fencing test'
);

DO $$
DECLARE
  v_cluster uuid;
  v_oid oid;
BEGIN
  SELECT cluster_id INTO STRICT v_cluster
    FROM powerops_security.cluster_identity WHERE singleton;
  SELECT oid INTO STRICT v_oid
    FROM pg_catalog.pg_roles WHERE rolname='pwr_gate1e_tenant_b';

  IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles
              WHERE oid=v_oid AND rolcanlogin) THEN
    RAISE EXCEPTION 'retired role still permits new logins';
  END IF;
  IF EXISTS (SELECT 1 FROM powerops_security.role_scope_binding
              WHERE cluster_id=v_cluster AND role_oid=v_oid AND active) THEN
    RAISE EXCEPTION 'retired scope binding remains active';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM powerops_security.retired_role_identity
                  WHERE cluster_id=v_cluster AND role_oid=v_oid
                    AND role_name='pwr_gate1e_tenant_b') THEN
    RAISE EXCEPTION 'retired identity tombstone is missing';
  END IF;
END
$$;
SQL

echo "[Gate 1G] PASS — disposable rollback, membership and retirement assertions completed"
