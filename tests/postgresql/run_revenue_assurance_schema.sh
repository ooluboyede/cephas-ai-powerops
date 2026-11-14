#!/usr/bin/env bash
set -Eeuo pipefail

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=postgres}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"
: "${POWEROPS_TEST_PASSWORD:=Gate1E-Disposable-Only-ChangeMe}"

admin() {
  PGPASSWORD="$PGPASSWORD" psql -X -v ON_ERROR_STOP=1 \
    -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"
}
role_sql() {
  local role="$1"; shift
  PGPASSWORD="$POWEROPS_TEST_PASSWORD" psql -X -v ON_ERROR_STOP=1 \
    -h "$PGHOST" -p "$PGPORT" -U "$role" -d "$PGDATABASE" "$@"
}

echo "[Revenue Assurance 0.1] Apply additive domain migration"
admin -f migrations/postgresql/0006_revenue_assurance_domain.sql

echo "[Revenue Assurance 0.1] Grant the new schema to existing active scoped test logins"
admin <<'SQL'
SELECT powerops_security.grant_revenue_assurance_access('pwr_gate1e_bu_a1');
SELECT powerops_security.grant_revenue_assurance_access('pwr_gate1e_bu_a2');

DO $$
BEGIN
  BEGIN
    PERFORM powerops_security.grant_revenue_assurance_access('pwr_gate1e_tenant_a');
    RAISE EXCEPTION 'FAIL: tenant-wide login unexpectedly received Revenue Assurance access';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
  BEGIN
    PERFORM powerops_security.grant_revenue_assurance_access('pwr_gate1e_tenant_b');
    RAISE EXCEPTION 'FAIL: tenant-wide login unexpectedly received Revenue Assurance access';
  EXCEPTION WHEN insufficient_privilege THEN
    NULL;
  END;
END
$$;
SQL

echo "[Revenue Assurance 0.1] Seed synthetic records in two business units"
admin <<'SQL'
INSERT INTO revenue_assurance.source_batches
(tenant_id,business_unit_id,batch_id,source_system,dataset_type,
 source_snapshot_hash,record_count,batch_status)
VALUES
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a1000000-0000-4000-8000-000000000001',
 'c1000000-0000-4000-8000-000000000001','synthetic-fixture','billing',
 repeat('a',64),1,'validated'),
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a2000000-0000-4000-8000-000000000002',
 'c2000000-0000-4000-8000-000000000002','synthetic-fixture','billing',
 repeat('b',64),1,'validated');

INSERT INTO revenue_assurance.findings
(tenant_id,business_unit_id,finding_id,batch_id,finding_code,category,currency,
 estimated_exposure,evidence_completeness,evidence_summary,recommendation,
 rule_version,calculation_version,idempotency_key,observed_at)
VALUES
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a1000000-0000-4000-8000-000000000001',
 'd1000000-0000-4000-8000-000000000001','c1000000-0000-4000-8000-000000000001',
 'BILLING_GAP','billing_gap','NGN',125000.0000,90,'Synthetic BU A1 evidence',
 'Validate billing cycle and account mapping','rules-0.1','calc-0.1','gate01-a1',now()),
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a2000000-0000-4000-8000-000000000002',
 'd2000000-0000-4000-8000-000000000002','c2000000-0000-4000-8000-000000000002',
 'BILLING_GAP','billing_gap','NGN',225000.0000,85,'Synthetic BU A2 evidence',
 'Validate billing cycle and account mapping','rules-0.1','calc-0.1','gate01-a2',now());

INSERT INTO revenue_assurance.audit_events
(tenant_id,business_unit_id,event_id,request_id,actor_subject,action,entity_type,entity_id)
VALUES
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','a1000000-0000-4000-8000-000000000001',
 'e1000000-0000-4000-8000-000000000001','req-gate01-a1','ci-fixture',
 'finding.seeded','finding','d1000000-0000-4000-8000-000000000001');
SQL

echo "[Revenue Assurance 0.1] Verify BU-scoped reads"
count_a1=$(role_sql pwr_gate1e_bu_a1 -Atc "SELECT count(*) FROM revenue_assurance.findings")
[[ "$count_a1" == "1" ]] || { echo "FAIL: BU A1 saw $count_a1 findings, expected 1" >&2; exit 1; }

count_a2=$(role_sql pwr_gate1e_bu_a2 -Atc "SELECT count(*) FROM revenue_assurance.findings")
[[ "$count_a2" == "1" ]] || { echo "FAIL: BU A2 saw $count_a2 findings, expected 1" >&2; exit 1; }

echo "[Revenue Assurance 0.1] Verify cross-BU insert is rejected by RLS"
if role_sql pwr_gate1e_bu_a1 -c "INSERT INTO revenue_assurance.source_batches
    (tenant_id,business_unit_id,batch_id,source_system,dataset_type,
     source_snapshot_hash,record_count,batch_status)
    VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
     'a2000000-0000-4000-8000-000000000002',
     'c3000000-0000-4000-8000-000000000003','attack','billing',
     repeat('c',64),1,'received')" >/dev/null 2>&1; then
  echo "FAIL: cross-BU insert unexpectedly succeeded" >&2
  exit 1
fi

echo "[Revenue Assurance 0.1] Verify audit rows are append-only"
if role_sql pwr_gate1e_bu_a1 -c "UPDATE revenue_assurance.audit_events SET action='tampered'
    WHERE event_id='e1000000-0000-4000-8000-000000000001'" >/dev/null 2>&1; then
  echo "FAIL: audit update unexpectedly succeeded" >&2
  exit 1
fi

echo "[Revenue Assurance 0.1] PASS — domain migration, BU RLS visibility, cross-BU write denial and audit immutability verified"
