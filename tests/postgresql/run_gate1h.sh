#!/usr/bin/env bash
set -Eeuo pipefail

# Gate 1H is disposable-only. Gate 1G remains a separate unresolved CI gate;
# this harness starts from the known Gate 1F fixture to isolate new assertions.
bash tests/postgresql/run_gate1f.sh

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

SESSION_ROLE="pwr_gate1h_session"
SESSION_PID=""
SESSION_CLIENT_PID=""
SESSION_OUTPUT="$(mktemp)"
SESSION_ERROR="$(mktemp)"
SESSION_INPUT="$(mktemp -u)"
mkfifo "$SESSION_INPUT"
cleanup() {
  if [[ -n "$SESSION_PID" ]]; then
    psql_admin -Atc "SELECT pg_terminate_backend($SESSION_PID) WHERE EXISTS (SELECT 1 FROM pg_stat_activity WHERE pid=$SESSION_PID)" >/dev/null 2>&1 || true
  fi
  if [[ -n "$SESSION_CLIENT_PID" ]]; then
    kill "$SESSION_CLIENT_PID" >/dev/null 2>&1 || true
    wait "$SESSION_CLIENT_PID" >/dev/null 2>&1 || true
  fi
  rm -f "$SESSION_OUTPUT" "$SESSION_ERROR" "$SESSION_INPUT"
}
trap cleanup EXIT

echo "[Gate 1H] Provision a disposable scoped login for session-fencing test"
psql_admin <<'SQL'
SELECT powerops_security.provision_scope_login(
  'pwr_gate1h_session',
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'tenant',
  NULL
);
ALTER ROLE pwr_gate1h_session PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
SQL

echo "[Gate 1H] Open and hold a real authenticated PostgreSQL session"
PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql -X -qAt \
  -h "$PGHOST" -p "$PGPORT" -U "$SESSION_ROLE" -d "$PGDATABASE" \
  <"$SESSION_INPUT" >"$SESSION_OUTPUT" 2>"$SESSION_ERROR" &
SESSION_CLIENT_PID=$!
exec 3>"$SESSION_INPUT"
printf '%s\n' 'SELECT pg_backend_pid();' >&3

for _ in $(seq 1 50); do
  if [[ -s "$SESSION_OUTPUT" ]]; then
    SESSION_PID="$(head -n 1 "$SESSION_OUTPUT" | tr -d '[:space:]')"
    if [[ "$SESSION_PID" =~ ^[0-9]+$ ]]; then break; fi
  fi
  sleep 0.2
done
[[ "$SESSION_PID" =~ ^[0-9]+$ ]] || {
  echo "Could not establish persistent scoped PostgreSQL session" >&2
  cat "$SESSION_ERROR" >&2
  exit 1
}
psql_admin -v pid="$SESSION_PID" -Atc \
  "SELECT 1 FROM pg_stat_activity WHERE pid=:'pid'::int AND usename='pwr_gate1h_session'" \
  | grep -qx '1'

echo "[Gate 1H] Retire login; existing backend remains connected but scope resolution fails"
psql_admin -c "SELECT powerops_security.retire_scope_login('pwr_gate1h_session','Gate 1H active session fencing test');"
psql_admin -v pid="$SESSION_PID" -Atc \
  "SELECT 1 FROM pg_stat_activity WHERE pid=:'pid'::int AND usename='pwr_gate1h_session'" \
  | grep -qx '1'

# These statements are sent through the SAME already-authenticated connection.
# psql continues after the expected SQL error because ON_ERROR_STOP is not set.
printf '%s\n' \
  'SELECT * FROM powerops_security.resolve_authenticated_scope();' \
  "SELECT 'SCOPE_CHECK_DONE';" \
  "SELECT 'SESSION_ALIVE:' || pg_backend_pid();" >&3
for _ in $(seq 1 50); do
  grep -q 'SCOPE_CHECK_DONE' "$SESSION_OUTPUT" && break
  sleep 0.2
done
grep -q 'SCOPE_CHECK_DONE' "$SESSION_OUTPUT" || {
  echo "Existing session did not complete the post-retirement scope check" >&2
  cat "$SESSION_ERROR" >&2
  exit 1
}
grep -q 'authenticated database identity is retired' "$SESSION_ERROR" || {
  echo "Existing session did not receive the expected retired-identity denial" >&2
  cat "$SESSION_ERROR" >&2
  exit 1
}
grep -q "SESSION_ALIVE:$SESSION_PID" "$SESSION_OUTPUT" || {
  echo "Existing session did not remain alive after resolver denial" >&2
  cat "$SESSION_OUTPUT" >&2
  exit 1
}

echo "[Gate 1H] Explicitly terminate retired backend and verify it is gone"
psql_admin -v pid="$SESSION_PID" -Atc \
  "SELECT pg_terminate_backend(:'pid'::int)" | grep -qx 't'
for _ in $(seq 1 50); do
  remaining="$(psql_admin -v pid="$SESSION_PID" -Atc \
    "SELECT count(*) FROM pg_stat_activity WHERE pid=:'pid'::int")"
  [[ "$remaining" == "0" ]] && break
  sleep 0.2
done
[[ "$remaining" == "0" ]] || {
  echo "Retired backend remained after pg_terminate_backend" >&2
  exit 1
}
exec 3>&-
wait "$SESSION_CLIENT_PID" >/dev/null 2>&1 || true
SESSION_CLIENT_PID=""
if psql_role "$SESSION_ROLE" -c 'SELECT 1' >/dev/null 2>&1; then
  echo "NOLOGIN retirement unexpectedly permitted a new connection" >&2
  exit 1
fi

echo "[Gate 1H] Verify FORCE RLS applies inside a SECURITY DEFINER owner path"
psql_admin <<'SQL'
CREATE ROLE powerops_gate1h_table_owner
  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;

GRANT USAGE ON SCHEMA powerops_data, powerops_security
  TO powerops_gate1h_table_owner;
GRANT EXECUTE ON FUNCTION powerops_security.resolve_authenticated_scope()
  TO powerops_gate1h_table_owner;
GRANT EXECUTE ON FUNCTION powerops_security.row_scope_permits(uuid, uuid)
  TO powerops_gate1h_table_owner;

CREATE TABLE powerops_data.gate1h_owner_probe (
  tenant_id uuid NOT NULL,
  business_unit_id uuid NOT NULL,
  probe_id integer NOT NULL,
  PRIMARY KEY (tenant_id, business_unit_id, probe_id)
);
INSERT INTO powerops_data.gate1h_owner_probe VALUES
 ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a1000000-0000-4000-8000-000000000001',1),
 ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a2000000-0000-4000-8000-000000000002',2),
 ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','b1000000-0000-4000-8000-000000000001',3);

ALTER TABLE powerops_data.gate1h_owner_probe
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE powerops_data.gate1h_owner_probe
  FORCE ROW LEVEL SECURITY;
CREATE POLICY gate1h_owner_probe_scope
  ON powerops_data.gate1h_owner_probe
  FOR ALL
  USING (powerops_security.row_scope_permits(tenant_id,business_unit_id))
  WITH CHECK (powerops_security.row_scope_permits(tenant_id,business_unit_id));
ALTER TABLE powerops_data.gate1h_owner_probe
  OWNER TO powerops_gate1h_table_owner;

CREATE FUNCTION powerops_data.gate1h_owner_visible_count()
RETURNS bigint
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_data
AS $function$
  SELECT count(*) FROM powerops_data.gate1h_owner_probe
$function$;
ALTER FUNCTION powerops_data.gate1h_owner_visible_count()
  OWNER TO powerops_gate1h_table_owner;
REVOKE ALL ON FUNCTION powerops_data.gate1h_owner_visible_count() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_data.gate1h_owner_visible_count()
  TO pwr_gate1e_bu_a1;
SQL

visible="$(psql_role pwr_gate1e_bu_a1 -Atc \
  'SELECT powerops_data.gate1h_owner_visible_count()')"
[[ "$visible" == "1" ]] || {
  echo "FORCE RLS SECURITY DEFINER owner path exposed $visible rows; expected 1" >&2
  exit 1
}

echo "[Gate 1H] PASS — active-session fencing and forced-RLS owner-path assertions completed"
