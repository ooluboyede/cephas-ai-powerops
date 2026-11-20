#!/usr/bin/env bash
set -Eeuo pipefail
: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=postgres}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"
: "${POWEROPS_TEST_PASSWORD:=Gate1E-Disposable-Only-ChangeMe}"
admin() { PGPASSWORD="$PGPASSWORD" psql -X -q -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"; }
actor() { local role="$1"; shift; PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql -X -q -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$role" -d "$PGDATABASE" "$@"; }

echo "[Gate PS-02.1A.3] Apply dedicated per-session login migration"
admin -f migrations/postgresql/0014_per_session_human_login_identity.sql

echo "[Gate PS-02.1A.3] Provision an isolated test actor, then two concurrent session identities"
admin <<'SQL'
SELECT powerops_security.provision_human_actor_login(
 'pwr_gate141a_actor',
 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
 'a1000000-0000-4000-8000-000000000001',
 'https://idp.customer.example/tenant-a',
 'human-operator-ps021a3',
 false,
 pg_catalog.clock_timestamp() + interval '10 minutes'
);
SELECT powerops_security.provision_human_session_login(
 'a1400000-0000-4000-8000-000000000001',
 'pwr_gate141a_sess_a',
 'https://idp.customer.example/tenant-a','human-operator-ps021a3',
 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
 'a1000000-0000-4000-8000-000000000001',
 pg_catalog.clock_timestamp() + interval '4 minutes');
SELECT powerops_security.provision_human_session_login(
 'a1400000-0000-4000-8000-000000000002',
 'pwr_gate141a_sess_b',
 'https://idp.customer.example/tenant-a','human-operator-ps021a3',
 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
 'a1000000-0000-4000-8000-000000000001',
 pg_catalog.clock_timestamp() + interval '4 minutes');
ALTER ROLE pwr_gate141a_sess_a PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
ALTER ROLE pwr_gate141a_sess_b PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
SQL

echo "[Gate PS-02.1A.3] Both independent logins resolve to the same DB-authoritative actor entitlements"
for role in pwr_gate141a_sess_a pwr_gate141a_sess_b; do
  resolved=$(actor "$role" -Atc "SELECT session_user || ':' || actor_subject || ':' || finance_operator || ':' || finance_verifier FROM powerops_security.resolve_authenticated_human_actor_v2()")
  [[ "$resolved" == "$role:https://idp.customer.example/tenant-a|human-operator-ps021a3:true:false" ]] || {
    echo "FAIL: per-session actor mapping mismatch for $role: $resolved" >&2; exit 1;
  }
done

echo "[Gate PS-02.1A.3] Session roles have distinct PostgreSQL OIDs and no unsafe role memberships"
role_oids=$(admin -Atc "SELECT count(DISTINCT role.oid) FROM pg_catalog.pg_roles role WHERE role.rolname IN ('pwr_gate141a_sess_a','pwr_gate141a_sess_b')")
[[ "$role_oids" == "2" ]] || { echo "FAIL: session logins do not have distinct role OIDs" >&2; exit 1; }
memberships=$(admin -Atc "SELECT count(*) FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles member_role ON member_role.oid=m.member JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor WHERE m.member IN (SELECT oid FROM pg_catalog.pg_roles WHERE rolname IN ('pwr_gate141a_sess_a','pwr_gate141a_sess_b')) OR (m.roleid IN (SELECT oid FROM pg_catalog.pg_roles WHERE rolname IN ('pwr_gate141a_sess_a','pwr_gate141a_sess_b')) AND (current_setting('server_version_num')::integer < 160000 OR member_role.rolname <> 'powerops_provisioner' OR NOT m.admin_option OR NOT grantor.rolsuper OR COALESCE((to_jsonb(m)->>'inherit_option')::boolean,true) OR COALESCE((to_jsonb(m)->>'set_option')::boolean,true)))")
[[ "$memberships" == "0" ]] || { echo "FAIL: session role has unsafe membership edges: $memberships" >&2; exit 1; }

echo "[Gate PS-02.1A.3] Runtime cannot read protected session-to-actor bindings"
if actor pwr_gate141a_sess_a -c 'SELECT * FROM powerops_security.human_session_actor_binding' >/tmp/powerops-ps021a3.out 2>&1; then
  echo "FAIL: session runtime read protected actor binding table" >&2; exit 1
fi

echo "[Gate PS-02.1A.3] Exact session retirement disables only the selected login"
admin -c "SELECT powerops_security.retire_human_session_login('a1400000-0000-4000-8000-000000000001','Gate PS-02.1A.3 exact-session retirement test')"
role_a_login=$(admin -Atc "SELECT rolcanlogin FROM pg_catalog.pg_roles WHERE rolname='pwr_gate141a_sess_a'")
role_b_login=$(admin -Atc "SELECT rolcanlogin FROM pg_catalog.pg_roles WHERE rolname='pwr_gate141a_sess_b'")
[[ "$role_a_login" == "f" && "$role_b_login" == "t" ]] || {
  echo "FAIL: exact retirement changed wrong login states: A=$role_a_login B=$role_b_login" >&2; exit 1;
}
remaining=$(actor pwr_gate141a_sess_b -Atc "SELECT actor_subject FROM powerops_security.resolve_authenticated_human_actor_v2()")
[[ "$remaining" == "https://idp.customer.example/tenant-a|human-operator-ps021a3" ]] || {
  echo "FAIL: unrelated session stopped resolving after exact retirement: $remaining" >&2; exit 1;
}

echo "[Gate PS-02.1A.3] Continue into the dependent PS-02.1A.5 backend registry integration gate"
bash tests/postgresql/run_gate0_5_14_8_6_ps021a5.sh

echo "[Gate PS-02.1A.3] Session role name and UUID tombstones prevent reuse"
if admin -c "SELECT powerops_security.provision_human_session_login('a1400000-0000-4000-8000-000000000001','pwr_gate141a_reuse','https://idp.customer.example/tenant-a','human-operator-ps021a3','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a1000000-0000-4000-8000-000000000001',pg_catalog.clock_timestamp()+interval '2 minutes')" >/tmp/powerops-ps021a3-reuse.out 2>&1; then
  echo "FAIL: retired session UUID was reused" >&2; exit 1
fi
if admin -c "SELECT powerops_security.provision_human_session_login('a1400000-0000-4000-8000-000000000003','pwr_gate141a_sess_a','https://idp.customer.example/tenant-a','human-operator-ps021a3','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a1000000-0000-4000-8000-000000000001',pg_catalog.clock_timestamp()+interval '2 minutes')" >/tmp/powerops-ps021a3-role-reuse.out 2>&1; then
  echo "FAIL: existing session role name was reused" >&2; exit 1
fi

echo "[Gate PS-02.1A.3] Actor-wide revocation retires every remaining session login"
admin -c "SELECT powerops_security.revoke_human_actor_login('pwr_gate141a_actor','Gate PS-02.1A.3 isolated actor-wide revocation test')"
role_b_after_actor_revoke=$(admin -Atc "SELECT rolcanlogin FROM pg_catalog.pg_roles WHERE rolname='pwr_gate141a_sess_b'")
[[ "$role_b_after_actor_revoke" == "f" ]] || {
  echo "FAIL: actor-wide revocation left a session login enabled" >&2; exit 1;
}
if actor pwr_gate141a_sess_b -c 'SELECT * FROM powerops_security.resolve_authenticated_human_actor_v2()' >/tmp/powerops-ps021a3-actor-revoked.out 2>&1; then
  echo "FAIL: session resolved after its actor was revoked" >&2; exit 1
fi

echo "[Gate PS-02.1A.3] PASS — dedicated session-role identity, actor entitlement mapping and exact login retirement validated"
