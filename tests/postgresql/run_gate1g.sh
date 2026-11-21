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

echo "[Gate 1G] Provision dedicated session identity"
admin <<'SQL'
SELECT powerops_security.provision_scope_login(
  'pwr_gate1g_session','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','business_unit',
  'a1000000-0000-4000-8000-000000000001');
ALTER ROLE pwr_gate1g_session PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
SQL

echo "[Gate 1G] Authenticated identity is immutable across role/GUC changes"
as_role pwr_gate1g_session <<'SQL'
DO $gate1g$
DECLARE
  baseline_count bigint;
  after_guc_count bigint;
BEGIN
  IF session_user <> 'pwr_gate1g_session' OR current_user <> 'pwr_gate1g_session' THEN
    RAISE EXCEPTION 'unexpected initial authenticated identity';
  END IF;

  -- Gate 1F inserts one additional same-scope A1 fixture row. Capture the
  -- authenticated baseline rather than assuming the earlier Gate 1E count.
  SELECT count(*) INTO baseline_count FROM powerops_data.feeders;
  IF baseline_count <> 2 THEN
    RAISE EXCEPTION 'unexpected Gate 1G baseline row count: %', baseline_count;
  END IF;

  PERFORM pg_catalog.set_config('app.tenant_id',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', true);
  PERFORM pg_catalog.set_config('app.business_unit_id',
    'b1000000-0000-4000-8000-000000000001', true);

  SELECT count(*) INTO after_guc_count FROM powerops_data.feeders;
  IF after_guc_count <> baseline_count THEN
    RAISE EXCEPTION
      'caller-controlled GUC changed scope; baseline was %, after GUC was %',
      baseline_count, after_guc_count;
  END IF;
  IF session_user <> 'pwr_gate1g_session' THEN
    RAISE EXCEPTION 'session_user changed after GUC manipulation';
  END IF;
END $gate1g$;
PREPARE gate1g_scope_probe AS SELECT count(*) FROM powerops_data.feeders;
EXECUTE gate1g_scope_probe;
DEALLOCATE gate1g_scope_probe;
SQL

echo "[Gate 1G] SET ROLE cannot borrow another tenant/BU identity"
if as_role pwr_gate1g_session -c 'SET ROLE pwr_gate1e_tenant_b' >/tmp/powerops-gate1g.out 2>&1; then
  echo "FAIL: scoped login changed into another scope role" >&2
  exit 1
fi
grep -q 'permission denied' /tmp/powerops-gate1g.out || {
  cat /tmp/powerops-gate1g.out >&2
  exit 1
}

echo "[Gate 1G] Retirement fences new logins; existing sessions require explicit termination"
PGAPPNAME=powerops_gate1g_retire_probe as_role pwr_gate1g_session -c 'SELECT pg_catalog.pg_sleep(60)' >/tmp/powerops-gate1g-session.out 2>&1 &
probe_pid=$!
cleanup() {
  admin -c "SELECT pg_catalog.pg_terminate_backend(pid) FROM pg_catalog.pg_stat_activity WHERE application_name='powerops_gate1g_retire_probe' AND pid <> pg_catalog.pg_backend_pid()" >/dev/null 2>&1 || true
  wait "$probe_pid" 2>/dev/null || true
}
trap cleanup EXIT

for attempt in $(seq 1 30); do
  active=$(admin -Atc "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE application_name='powerops_gate1g_retire_probe'")
  [[ "$active" -ge 1 ]] && break
  sleep 1
done
[[ "${active:-0}" -ge 1 ]] || {
  echo "FAIL: retirement probe session did not start" >&2
  cat /tmp/powerops-gate1g-session.out >&2
  exit 1
}

admin -c "SELECT powerops_security.retire_scope_login('pwr_gate1g_session','Gate 1G session revocation test')" >/dev/null
remaining=$(admin -Atc "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE application_name='powerops_gate1g_retire_probe'")
if [[ "$remaining" -ne 1 ]]; then
  echo "FAIL: expected one existing session before explicit termination, found $remaining" >&2
  exit 1
fi
admin -c "SELECT pg_catalog.pg_terminate_backend(pid) FROM pg_catalog.pg_stat_activity WHERE application_name='powerops_gate1g_retire_probe' AND pid <> pg_catalog.pg_backend_pid()" >/dev/null
for attempt in $(seq 1 30); do
  remaining=$(admin -Atc "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE application_name='powerops_gate1g_retire_probe'")
  [[ "$remaining" -eq 0 ]] && break
  sleep 1
done
[[ "$remaining" -eq 0 ]] || {
  echo "FAIL: retired identity still has an active session" >&2
  exit 1
}
wait "$probe_pid" 2>/dev/null || true
if as_role pwr_gate1g_session -c 'SELECT 1' >/tmp/powerops-gate1g-login.out 2>&1; then
  echo "FAIL: retired NOLOGIN identity accepted a new connection" >&2
  exit 1
fi

echo "[Gate 1G] PASS — session identity and explicit retirement fencing assertions executed"
echo "[Gate 1G] NOTE — this does not test PgBouncer/ODBC/JDBC pool implementations or production pool eviction."
