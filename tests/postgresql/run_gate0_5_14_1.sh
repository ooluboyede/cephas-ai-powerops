#!/usr/bin/env bash
set -Eeuo pipefail
: "\${PGHOST:=127.0.0.1}"
: "\${PGPORT:=5432}"
: "\${PGDATABASE:=postgres}"
: "\${PGUSER:=postgres}"
: "\${PGPASSWORD:=postgres}"
: "\${POWEROPS_TEST_PASSWORD:=Gate1E-Disposable-Only-ChangeMe}"
admin() { PGPASSWORD="$PGPASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"; }
actor() { local role="$1"; shift; PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$role" -d "$PGDATABASE" "$@"; }

echo "[Gate 0.5.14.1] Apply protected human actor mapping migration"
admin -f migrations/postgresql/0010_human_actor_identity_foundation.sql

echo "[Gate 0.5.14.1] Provision separate maker and finance-verifier principals"
admin <<'SQL'
SELECT powerops_security.provision_human_actor_login(
 'pwr_gate014_maker','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
 'a1000000-0000-4000-8000-000000000001',
 'https://idp.customer.example/tenant-a','human-maker-001',false);
SELECT powerops_security.provision_human_actor_login(
 'pwr_gate014_verifier','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
 'a1000000-0000-4000-8000-000000000001',
 'https://idp.customer.example/tenant-a','human-verifier-002',true);
ALTER ROLE pwr_gate014_maker PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
ALTER ROLE pwr_gate014_verifier PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
SQL

maker=$(actor pwr_gate014_maker -Atc "SELECT actor_subject || ':' || finance_verifier FROM powerops_security.resolve_authenticated_human_actor()")
[[ "$maker" == "https://idp.customer.example/tenant-a|human-maker-001:false" ]] || { echo "FAIL: maker mapping mismatch: $maker" >&2; exit 1; }
verifier=$(actor pwr_gate014_verifier -Atc "SELECT actor_subject || ':' || finance_verifier FROM powerops_security.resolve_authenticated_human_actor()")
[[ "$verifier" == "https://idp.customer.example/tenant-a|human-verifier-002:true" ]] || { echo "FAIL: verifier mapping mismatch: $verifier" >&2; exit 1; }

echo "[Gate 0.5.14.1] GUC spoof cannot change actor or entitlement"
spoof=$(actor pwr_gate014_maker -Atc "SELECT set_config('app.actor_subject','attacker|finance-admin',false); SELECT set_config('app.finance_verifier','true',false); SELECT actor_subject || ':' || finance_verifier FROM powerops_security.resolve_authenticated_human_actor()" | tail -n 1)
[[ "$spoof" == "https://idp.customer.example/tenant-a|human-maker-001:false" ]] || { echo "FAIL: GUC spoof changed actor: $spoof" >&2; exit 1; }

echo "[Gate 0.5.14.1] Runtime cannot read or mutate actor registry"
for sql in "SELECT * FROM powerops_security.human_actor_binding" "UPDATE powerops_security.human_actor_binding SET finance_verifier=true" "DELETE FROM powerops_security.human_actor_binding"; do
  if actor pwr_gate014_maker -c "$sql" >/tmp/powerops-gate014.out 2>&1; then
    echo "FAIL: runtime accessed protected actor registry: $sql" >&2; exit 1
  fi
done

echo "[Gate 0.5.14.1] SET ROLE escalation denied"
if actor pwr_gate014_maker -c 'SET ROLE pwr_gate014_verifier' >/tmp/powerops-gate014.out 2>&1; then
  echo "FAIL: maker switched to verifier role" >&2; exit 1
fi
grep -q 'permission denied' /tmp/powerops-gate014.out || { cat /tmp/powerops-gate014.out >&2; exit 1; }

echo "[Gate 0.5.14.1] Expired actor provisioning rejected atomically"
admin <<'SQL'
DO $$
BEGIN
  BEGIN
    PERFORM powerops_security.provision_human_actor_login(
      'pwr_gate014_expired','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      'a1000000-0000-4000-8000-000000000001',
      'https://idp.customer.example/tenant-a','human-expired-003',false,
      now() - interval '1 minute');
    RAISE EXCEPTION 'FAIL: expired actor provisioning succeeded';
  EXCEPTION WHEN invalid_parameter_value THEN NULL;
  END;
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='pwr_gate014_expired') THEN
    RAISE EXCEPTION 'FAIL: failed provisioning left a role behind';
  END IF;
END $$;
SQL

echo "[Gate 0.5.14.1] Revocation disables actor mapping and login"
admin -c "SELECT powerops_security.revoke_human_actor_login('pwr_gate014_maker','Gate 0.5.14.1 synthetic revocation test')" >/dev/null
admin -c "DO \$\$ BEGIN IF EXISTS (SELECT 1 FROM powerops_security.human_actor_binding WHERE subject='human-maker-001' AND active) THEN RAISE EXCEPTION 'revoked actor remains active'; END IF; IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='pwr_gate014_maker' AND rolcanlogin) THEN RAISE EXCEPTION 'revoked actor login still permits new sessions'; END IF; END \$\$"

echo "[Gate 0.5.14.1] PASS — protected human actor identity foundation validated"
