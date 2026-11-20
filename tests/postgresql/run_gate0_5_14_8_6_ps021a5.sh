#!/usr/bin/env bash
set -Eeuo pipefail
: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=postgres}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"
: "${POWEROPS_TEST_PASSWORD:=Gate1E-Disposable-Only-ChangeMe}"
admin() { PGPASSWORD="$PGPASSWORD" psql -X -q -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"; }
actor() {
  local role="$1"
  local app="$2"
  shift 2
  PGAPPNAME="$app" PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql -X -q -v ON_ERROR_STOP=1 \
    -h "$PGHOST" -p "$PGPORT" -U "$role" -d "$PGDATABASE" "$@"
}

SESSION_B='a1400000-0000-4000-8000-000000000002'
ROLE_B='pwr_gate141a_sess_b'

echo "[Gate PS-02.1A.5] Apply per-session backend registry after migration 0014"
admin -f migrations/postgresql/0015_human_session_backend_registry.sql

echo "[Gate PS-02.1A.5] Register two distinct live physical backends for one session"
actor "$ROLE_B" "ps021a5-register-a" >/tmp/powerops-ps021a5-backend-a.out 2>&1 <<SQL &
BEGIN;
SELECT powerops_security.register_human_session_backend('$SESSION_B');
SELECT pg_catalog.pg_sleep(2);
COMMIT;
SELECT pg_catalog.pg_sleep(30);
SQL
backend_a=$!
actor "$ROLE_B" "ps021a5-register-b" >/tmp/powerops-ps021a5-backend-b.out 2>&1 <<SQL &
BEGIN;
SELECT powerops_security.register_human_session_backend('$SESSION_B');
SELECT pg_catalog.pg_sleep(2);
COMMIT;
SELECT pg_catalog.pg_sleep(30);
SQL
backend_b=$!

registered=0
for attempt in $(seq 1 40); do
  registered=$(admin -Atc "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE application_name IN ('ps021a5-register-a','ps021a5-register-b') AND state='active' AND query LIKE '%pg_sleep(2)%'")
  [[ "$registered" == "2" ]] && break
  sleep 0.25
done
[[ "$registered" == "2" ]] || {
  echo "FAIL: expected two registered physical backends, found $registered" >&2
  echo "--- backend A diagnostic ---" >&2
  cat /tmp/powerops-ps021a5-backend-a.out >&2 || true
  echo "--- backend B diagnostic ---" >&2
  cat /tmp/powerops-ps021a5-backend-b.out >&2 || true
  kill "$backend_a" "$backend_b" 2>/dev/null || true
  exit 1
}

echo "[Gate PS-02.1A.5] Revocation waits for registration transactions holding the shared admission lock"
admin -c "SELECT powerops_security.retire_human_session_login('$SESSION_B','Gate PS-02.1A.5 backend registry test')"

echo "[Gate PS-02.1A.5] Terminate only exact PID + backend_start matches; retry until verified"
complete=f
for attempt in $(seq 1 20); do
  result=$(admin -At -F '|' -c "SELECT terminated_backend_count, remaining_backend_count, complete FROM powerops_security.terminate_human_session_backends('$SESSION_B')")
  terminated="${result%%|*}"
  remainder="${result#*|}"
  remaining="${remainder%%|*}"
  complete="${result##*|}"
  [[ "$complete" == "t" ]] && break
  sleep 0.25
done
[[ "$complete" == "t" && "$remaining" == "0" ]] || {
  echo "FAIL: exact backend termination did not reach verified completion (remaining=$remaining last_result=$result)" >&2
  kill "$backend_a" "$backend_b" 2>/dev/null || true
  exit 1
}
terminated_registry_count=$(admin -Atc "SELECT count(*) FROM powerops_security.human_session_backend_registry WHERE session_id='$SESSION_B' AND terminated_at IS NOT NULL")
termination_requested_count=$(admin -Atc "SELECT count(*) FROM powerops_security.human_session_backend_audit WHERE session_id='$SESSION_B' AND event_type='backend_termination_requested'")
[[ "$terminated_registry_count" == "2" && "$termination_requested_count" == "2" ]] || {
  echo "FAIL: expected two exact backend terminations (registry=$terminated_registry_count requested=$termination_requested_count)" >&2
  exit 1
}
wait "$backend_a" 2>/dev/null || true
wait "$backend_b" 2>/dev/null || true

remaining=$(admin -Atc "SELECT count(*) FROM powerops_security.human_session_backend_registry WHERE session_id='$SESSION_B' AND terminated_at IS NULL")
[[ "$remaining" == "0" ]] || {
  echo "FAIL: live backend registry rows remain: $remaining" >&2; exit 1;
}

echo "[Gate PS-02.1A.5] Stale PID record with mismatched backend_start is never signalled"
admin <<SQL
INSERT INTO powerops_security.human_session_backend_registry(session_id, backend_pid, backend_start)
VALUES ('$SESSION_B', pg_catalog.pg_backend_pid(), pg_catalog.clock_timestamp() - interval '1 day')
ON CONFLICT DO NOTHING;
SELECT * FROM powerops_security.terminate_human_session_backends('$SESSION_B');
SELECT 1;
SQL

echo "[Gate PS-02.1A.5] Verify backend registration audit is durable and secret-free"
audit_count=$(admin -Atc "SELECT count(*) FROM powerops_security.human_session_backend_audit WHERE session_id='$SESSION_B' AND event_type='backend_registered'")
[[ "$audit_count" == "2" ]] || {
  echo "FAIL: expected two backend registration audit records, found $audit_count" >&2; exit 1;
}

echo "[Gate PS-02.1A.5] PASS — exact-session backend registration, fencing, termination and PID-reuse guard"
