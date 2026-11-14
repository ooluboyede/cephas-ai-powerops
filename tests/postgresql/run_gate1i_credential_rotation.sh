#!/usr/bin/env bash
set -Eeuo pipefail

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=postgres}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"
: "${PGBOUNCER_PORT:=6433}"
: "${OLD_PASSWORD:=Gate1I-Old-Disposable-Only}"
: "${NEW_PASSWORD:=Gate1I-New-Disposable-Only}"

admin() {
  PGPASSWORD="$PGPASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"
}
client() {
  local password="$1"; shift
  PGPASSWORD="$password" psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -p "$PGBOUNCER_PORT" -U pwr_gate1i_a1 -d "$PGDATABASE" "$@"
}
pool_admin() {
  PGPASSWORD="$PGPASSWORD" psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -p "$PGBOUNCER_PORT" -U postgres -d pgbouncer "$@"
}

echo "[Gate 1I] Provision disposable BU identity and initial credential"
admin <<SQL
SELECT powerops_security.provision_scope_login(
 'pwr_gate1i_a1','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','business_unit',
 'a1000000-0000-4000-8000-000000000001');
ALTER ROLE pwr_gate1i_a1 PASSWORD '$OLD_PASSWORD';
SQL

workdir=$(mktemp -d)
pgbouncer_pid=""
cleanup() {
  if [[ -n "$pgbouncer_pid" ]]; then
    kill "$pgbouncer_pid" 2>/dev/null || true
    wait "$pgbouncer_pid" 2>/dev/null || true
  fi
  rm -rf "$workdir"
}
trap cleanup EXIT

write_auth_file() {
  local password="$1"
  cat >"$workdir/userlist.txt.tmp" <<EOF
"postgres" "$PGPASSWORD"
"pwr_gate1i_a1" "$password"
EOF
  chmod 600 "$workdir/userlist.txt.tmp"
  mv "$workdir/userlist.txt.tmp" "$workdir/userlist.txt"
}
write_auth_file "$OLD_PASSWORD"

cat >"$workdir/pgbouncer.ini" <<EOF
[databases]
$PGDATABASE = host=$PGHOST port=$PGPORT dbname=$PGDATABASE

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = $PGBOUNCER_PORT
auth_type = plain
auth_file = $workdir/userlist.txt
pool_mode = transaction
max_client_conn = 30
default_pool_size = 1
reserve_pool_size = 0
server_reset_query = DISCARD ALL
server_reset_query_always = 1
admin_users = postgres
logfile = $workdir/pgbouncer.log
pidfile = $workdir/pgbouncer.pid
EOF

echo "[Gate 1I] Start disposable PgBouncer"
pgbouncer "$workdir/pgbouncer.ini" >"$workdir/pgbouncer-startup.log" 2>&1 &
pgbouncer_pid=$!
for attempt in $(seq 1 30); do
  if client "$OLD_PASSWORD" -Atc 'SELECT 1' >/dev/null 2>&1; then break; fi
  sleep 1
done
client "$OLD_PASSWORD" -Atc 'SELECT 1' >/dev/null
before=$(client "$OLD_PASSWORD" -At -c "SELECT session_user, (SELECT count(*) FROM powerops_data.feeders)")
[[ "$before" == "pwr_gate1i_a1|1" ]] || { echo "FAIL: initial scope check: $before" >&2; exit 1; }

echo "[Gate 1I] Rotate database credential and atomically replace PgBouncer auth file"
admin -c "ALTER ROLE pwr_gate1i_a1 PASSWORD '$NEW_PASSWORD'"
write_auth_file "$NEW_PASSWORD"
pool_admin -c "RELOAD"
pool_admin -c "RECONNECT $PGDATABASE"

echo "[Gate 1I] Verify old credential is rejected after auth reload"
if client "$OLD_PASSWORD" -Atc 'SELECT 1' >"$workdir/old.out" 2>"$workdir/old.err"; then
  echo "FAIL: old credential unexpectedly authenticated after RELOAD" >&2
  exit 1
fi

echo "[Gate 1I] Verify new credential authenticates and retains database-derived scope"
after=$(client "$NEW_PASSWORD" -At -c "SELECT session_user, (SELECT count(*) FROM powerops_data.feeders)")
[[ "$after" == "pwr_gate1i_a1|1" ]] || { echo "FAIL: rotated credential scope check: $after" >&2; exit 1; }

echo "[Gate 1I] Terminate any remaining backend sessions for the retired credential generation"
admin -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename='pwr_gate1i_a1' AND pid <> pg_backend_pid()"
pool_admin -c "RECONNECT $PGDATABASE"
remaining=$(admin -At -c "SELECT count(*) FROM pg_stat_activity WHERE usename='pwr_gate1i_a1' AND pid <> pg_backend_pid()")
[[ "$remaining" == "0" ]] || { echo "FAIL: stale database sessions remain: $remaining" >&2; exit 1; }

echo "[Gate 1I] PASS — disposable credential rotation, auth reload, old-secret rejection and backend-session fencing executed"
echo "[Gate 1I] LIMIT — customer secret-manager integration, concurrent in-flight transactions, HA poolers and production credential rollout remain unvalidated."
