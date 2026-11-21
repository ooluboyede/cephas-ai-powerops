#!/usr/bin/env bash
set -Eeuo pipefail

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=postgres}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"
: "${POWEROPS_TEST_PASSWORD:=Gate1E-Disposable-Only-ChangeMe}"

admin() {
  PGPASSWORD="$PGPASSWORD" psql -X -q -v ON_ERROR_STOP=1 \
    -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"
}
admin_app() {
  local app="$1"
  shift
  PGAPPNAME="$app" PGPASSWORD="$PGPASSWORD" psql -X -q -v ON_ERROR_STOP=1 \
    -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"
}
actor() {
  PGAPPNAME=ps021a9-registration PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql \
    -X -q -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" \
    -U pwr_gate_ps021a9_session -d "$PGDATABASE" "$@"
}

SESSION_ID='a1400000-0000-4000-8000-000000000009'
ACTOR_ROLE='pwr_gate_ps021a9_actor'
SESSION_ROLE='pwr_gate_ps021a9_session'

echo "[Gate PS-02.1A.9] Provision an isolated actor and dedicated session login"
admin <<SQL
SELECT powerops_security.provision_human_actor_login_v2(
    '$ACTOR_ROLE',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'a1000000-0000-4000-8000-000000000001',
    'https://idp.customer.example/tenant-a',
    'human-operator-ps021a9',
    true,
    false,
    pg_catalog.clock_timestamp() + interval '10 minutes'
);
SELECT powerops_security.provision_human_session_login(
    '$SESSION_ID',
    '$SESSION_ROLE',
    'https://idp.customer.example/tenant-a',
    'human-operator-ps021a9',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'a1000000-0000-4000-8000-000000000001',
    pg_catalog.clock_timestamp() + interval '4 minutes'
);
ALTER ROLE $SESSION_ROLE PASSWORD '$POWEROPS_TEST_PASSWORD';
SQL

echo "[Gate PS-02.1A.9] Authenticate registration connection before revocation"
actor >/tmp/powerops-ps021a9-registration.out 2>&1 <<SQL &
BEGIN;
SELECT pg_catalog.pg_sleep(2);
SELECT powerops_security.register_human_session_backend('$SESSION_ID');
COMMIT;
SQL
registration_pid=$!

ready=0
for attempt in $(seq 1 100); do
  ready=$(admin -Atc "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE application_name='ps021a9-registration' AND state='active' AND query LIKE '%pg_sleep(2)%'")
  [[ "$ready" == "1" ]] && break
  sleep 0.05
done
[[ "$ready" == "1" ]] || {
  echo "FAIL: registration connection did not reach its pre-revocation barrier" >&2
  cat /tmp/powerops-ps021a9-registration.out >&2 || true
  kill "$registration_pid" 2>/dev/null || true
  exit 1
}

echo "[Gate PS-02.1A.9] Acquire revocation fence before registration attempts its shared lock"
admin_app ps021a9-revocation >/tmp/powerops-ps021a9-revocation.out 2>&1 <<SQL &
BEGIN;
SELECT powerops_security.retire_human_session_login(
    '$SESSION_ID',
    'Gate PS-02.1A.9 revocation-first race test'
);
SELECT pg_catalog.pg_sleep(5);
COMMIT;
SQL
revocation_pid=$!

locked=0
for attempt in $(seq 1 100); do
  locked=$(admin -Atc "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE application_name='ps021a9-revocation' AND state='active' AND query LIKE '%pg_sleep(5)%'")
  [[ "$locked" == "1" ]] && break
  sleep 0.05
done
[[ "$locked" == "1" ]] || {
  echo "FAIL: revocation did not acquire and hold the session fence lock" >&2
  cat /tmp/powerops-ps021a9-revocation.out >&2 || true
  kill "$registration_pid" "$revocation_pid" 2>/dev/null || true
  exit 1
}

echo "[Gate PS-02.1A.9] Registration must wait, then fail after the revocation commit"
if wait "$registration_pid"; then
  echo "FAIL: registration succeeded after revocation had acquired the fence lock" >&2
  cat /tmp/powerops-ps021a9-registration.out >&2 || true
  kill "$revocation_pid" 2>/dev/null || true
  exit 1
fi
wait "$revocation_pid"

grep -q "human session is unknown, expired, revoked, or bound to another login" \
  /tmp/powerops-ps021a9-registration.out || {
    echo "FAIL: registration did not fail for the expected revoked-session reason" >&2
    cat /tmp/powerops-ps021a9-registration.out >&2 || true
    exit 1
  }

registry_count=$(admin -Atc "SELECT count(*) FROM powerops_security.human_session_backend_registry WHERE session_id='$SESSION_ID'")
audit_count=$(admin -Atc "SELECT count(*) FROM powerops_security.human_session_backend_audit WHERE session_id='$SESSION_ID' AND event_type='backend_registered'")
[[ "$registry_count" == "0" && "$audit_count" == "0" ]] || {
  echo "FAIL: revocation-first race left registration evidence (registry=$registry_count audit=$audit_count)" >&2
  exit 1
}

echo "PS-02.1A.9 PASS — revocation-first admission fence wins over concurrent registration"
