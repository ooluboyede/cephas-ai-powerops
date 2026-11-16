#!/usr/bin/env bash
set -Eeuo pipefail

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=postgres}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"
: "${POWEROPS_TEST_PASSWORD:=Gate1E-Disposable-Only-ChangeMe}"
: "${PGBOUNCER_PORT:=6543}"

admin() {
  PGPASSWORD="$PGPASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"
}
pool_role() {
  local role="$1"; shift
  PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -p "$PGBOUNCER_PORT" -U "$role" -d "$PGDATABASE" "$@"
}

echo "[Gate 1H] Provision two independent scope logins"
admin <<'SQL'
SELECT powerops_security.provision_scope_login(
 'pwr_gate1h_a1','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','business_unit',
 'a1000000-0000-4000-8000-000000000001');
SELECT powerops_security.provision_scope_login(
 'pwr_gate1h_b1','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','business_unit',
 'b1000000-0000-4000-8000-000000000001');
ALTER ROLE pwr_gate1h_a1 PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
ALTER ROLE pwr_gate1h_b1 PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
SQL

if ! command -v pgbouncer >/dev/null 2>&1; then
  echo "FAIL: pgbouncer executable is unavailable" >&2
  exit 1
fi

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

cat >"$workdir/userlist.txt" <<EOF
"pwr_gate1h_a1" "$POWEROPS_TEST_PASSWORD"
"pwr_gate1h_b1" "$POWEROPS_TEST_PASSWORD"
EOF
chmod 600 "$workdir/userlist.txt"

cat >"$workdir/pgbouncer.ini" <<EOF
[databases]
$PGDATABASE = host=$PGHOST port=$PGPORT dbname=$PGDATABASE

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = $PGBOUNCER_PORT
auth_type = plain
auth_file = $workdir/userlist.txt
pool_mode = transaction
max_client_conn = 50
default_pool_size = 1
reserve_pool_size = 0
server_reset_query = DISCARD ALL
server_reset_query_always = 1
admin_users = $PGUSER
logfile = $workdir/pgbouncer.log
pidfile = $workdir/pgbouncer.pid
EOF

echo "[Gate 1H] Start PgBouncer in transaction-pooling mode"
pgbouncer "$workdir/pgbouncer.ini" >"$workdir/pgbouncer-startup.log" 2>&1 &
pgbouncer_pid=$!
probe_log="$workdir/pgbouncer-probe.log"
for attempt in $(seq 1 30); do
  if PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql -X -h 127.0.0.1 -p "$PGBOUNCER_PORT" -U pwr_gate1h_a1 -d "$PGDATABASE" -Atc 'SELECT 1' >"$probe_log" 2>&1; then
    break
  fi
  if ! kill -0 "$pgbouncer_pid" 2>/dev/null; then
    break
  fi
  sleep 1
done
if ! PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql -X -h 127.0.0.1 -p "$PGBOUNCER_PORT" -U pwr_gate1h_a1 -d "$PGDATABASE" -Atc 'SELECT 1' >"$probe_log" 2>&1; then
  cat "$workdir/pgbouncer-startup.log" "$workdir/pgbouncer.log" "$probe_log" 2>/dev/null >&2
  echo "FAIL: PgBouncer did not become ready on 127.0.0.1:$PGBOUNCER_PORT" >&2
  exit 1
fi

assert_scope() {
  local role="$1" expected="$2" actual
  actual=$(pool_role "$role" -At -F '|' -c "SELECT session_user, (SELECT count(*) FROM powerops_data.feeders)")
  [[ "$actual" == "$role|$expected" ]] || {
    echo "FAIL: expected $role|$expected through PgBouncer, received: $actual" >&2
    exit 1
  }
}

echo "[Gate 1H] Alternate distinct authenticated identities through a one-server transaction pool"
for attempt in $(seq 1 12); do
  assert_scope pwr_gate1h_a1 1
  assert_scope pwr_gate1h_b1 1
done

echo "[Gate 1H] Caller-controlled GUCs cannot alter either pooled identity"
spoof_a=$(pool_role pwr_gate1h_a1 -At -F '|' -c "SET app.tenant_id='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'; SELECT session_user, (SELECT count(*) FROM powerops_data.feeders)")
[[ "$spoof_a" == "pwr_gate1h_a1|1" ]] || {
  echo "FAIL: A1 scope changed through GUC manipulation: $spoof_a" >&2
  exit 1
}
spoof_b=$(pool_role pwr_gate1h_b1 -At -F '|' -c "SET app.tenant_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'; SELECT session_user, count(*) FROM powerops_data.feeders")
[[ "$spoof_b" == "pwr_gate1h_b1|1" ]] || {
  echo "FAIL: B1 scope changed through GUC manipulation: $spoof_b" >&2
  exit 1
}

echo "[Gate 1H] PASS — PgBouncer transaction-pool identity and row-scope checks executed"
echo "[Gate 1H] LIMIT — this is a disposable CI pool; production pooler configuration and credential rotation still require customer-specific validation."
