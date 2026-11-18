#!/usr/bin/env bash
set -Eeuo pipefail
: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=postgres}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"
: "${POWEROPS_TEST_PASSWORD:=Gate1E-Disposable-Only-ChangeMe}"
admin() { PGPASSWORD="$PGPASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"; }
actor() { local role="$1"; shift; PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$role" -d "$PGDATABASE" "$@"; }

echo "[Gate 0.5.14.4] Apply distinct finance entitlement migration"
admin -f migrations/postgresql/0011_human_finance_entitlements.sql

echo "[Gate 0.5.14.4] Provision separate finance maker and verifier roles"
admin <<'SQL'
SELECT powerops_security.provision_human_actor_login_v2(
 'pwr_gate0144_operator','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
 'a1000000-0000-4000-8000-000000000001',
 'https://idp.customer.example/tenant-a','human-operator-0144',true,false,NULL);
SELECT powerops_security.provision_human_actor_login_v2(
 'pwr_gate0144_verifier','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
 'a1000000-0000-4000-8000-000000000001',
 'https://idp.customer.example/tenant-a','human-verifier-0144',false,true,NULL);
ALTER ROLE pwr_gate0144_operator PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
ALTER ROLE pwr_gate0144_verifier PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
SQL

operator=$(actor pwr_gate0144_operator -Atc "SELECT actor_subject || ':' || finance_operator || ':' || finance_verifier FROM powerops_security.resolve_authenticated_human_actor_v2()")
[[ "$operator" == "https://idp.customer.example/tenant-a|human-operator-0144:true:false" ]] || { echo "FAIL: operator mapping mismatch: $operator" >&2; exit 1; }
verifier=$(actor pwr_gate0144_verifier -Atc "SELECT actor_subject || ':' || finance_operator || ':' || finance_verifier FROM powerops_security.resolve_authenticated_human_actor_v2()")
[[ "$verifier" == "https://idp.customer.example/tenant-a|human-verifier-0144:false:true" ]] || { echo "FAIL: verifier mapping mismatch: $verifier" >&2; exit 1; }

echo "[Gate 0.5.14.4] Maker cannot spoof verifier entitlement with GUC"
spoof=$(actor pwr_gate0144_operator -Atc "SELECT set_config('app.finance_operator','false',false); SELECT set_config('app.finance_verifier','true',false); SELECT finance_operator || ':' || finance_verifier FROM powerops_security.resolve_authenticated_human_actor_v2()" | tail -n 1)
[[ "$spoof" == "true:false" ]] || { echo "FAIL: GUC spoof changed finance entitlements: $spoof" >&2; exit 1; }

echo "[Gate 0.5.14.4] Dual maker/verifier provisioning rejected atomically"
admin <<'SQL'
DO $$
BEGIN
  BEGIN
    PERFORM powerops_security.provision_human_actor_login_v2(
      'pwr_gate0144_dual','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      'a1000000-0000-4000-8000-000000000001',
      'https://idp.customer.example/tenant-a','human-dual-0144',true,true,NULL);
    RAISE EXCEPTION 'FAIL: dual finance entitlement provisioning succeeded';
  EXCEPTION WHEN invalid_parameter_value THEN NULL;
  END;
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='pwr_gate0144_dual') THEN
    RAISE EXCEPTION 'FAIL: rejected dual entitlement provisioning left a role behind';
  END IF;
END $$;
SQL

echo "[Gate 0.5.14.4] Runtime cannot access protected actor registry"
if actor pwr_gate0144_operator -c 'SELECT * FROM powerops_security.human_actor_binding' >/tmp/powerops-gate0144.out 2>&1; then
  echo "FAIL: runtime read protected actor registry" >&2; exit 1
fi

echo "[Gate 0.5.14.4] SET ROLE escalation denied"
if actor pwr_gate0144_operator -c 'SET ROLE pwr_gate0144_verifier' >/tmp/powerops-gate0144.out 2>&1; then
  echo "FAIL: finance maker switched to finance verifier" >&2; exit 1
fi
grep -q 'permission denied' /tmp/powerops-gate0144.out || { cat /tmp/powerops-gate0144.out >&2; exit 1; }

echo "[Gate 0.5.14.4] PASS — database-enforced finance entitlements validated"
