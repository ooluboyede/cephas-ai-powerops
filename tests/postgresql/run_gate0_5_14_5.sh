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

echo "[Gate 0.5.14.5] Apply database-derived recovery and audit actor triggers"
admin -f migrations/postgresql/0012_database_derived_finance_actors.sql

echo "[Gate 0.5.14.5] Seed an approved investigation case"
admin <<'SQL'
INSERT INTO revenue_assurance.investigation_cases
(tenant_id,business_unit_id,case_id,finding_id,case_status,summary,opening_reason,created_by)
VALUES
('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
 'a1000000-0000-4000-8000-000000000001',
 'f5000000-0000-4000-8000-000000000005',
 'd1000000-0000-4000-8000-000000000001',
 'approved',
 'Gate 0.5.14.5 actor binding fixture',
 'Synthetic approved case for database-derived actor tests',
 'ci-setup-fixture');
SQL

echo "[Gate 0.5.14.5] Finance maker cannot spoof recorded_by"
maker_actor=$(actor pwr_gate0144_operator -Atc "
  INSERT INTO revenue_assurance.recovery_outcomes
  (tenant_id,business_unit_id,outcome_id,case_id,amount,currency,outcome,evidence_reference,recorded_by)
  VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
   'a1000000-0000-4000-8000-000000000001',
   'f5100000-0000-4000-8000-000000000005',
   'f5000000-0000-4000-8000-000000000005',
   1000.0000,'NGN','reported','synthetic-bank-receipt','forged|attacker')
  RETURNING recorded_by")
[[ "$maker_actor" == "https://idp.customer.example/tenant-a|human-operator-0144" ]] || {
  echo "FAIL: database did not replace forged maker identity: $maker_actor" >&2; exit 1;
}

echo "[Gate 0.5.14.5] Finance verifier cannot spoof verifier_subject"
verifier_actor=$(actor pwr_gate0144_verifier -Atc "
  INSERT INTO revenue_assurance.recovery_verifications
  (tenant_id,business_unit_id,verification_id,outcome_id,verifier_subject,evidence_reference,reason)
  VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
   'a1000000-0000-4000-8000-000000000001',
   'f5200000-0000-4000-8000-000000000005',
   'f5100000-0000-4000-8000-000000000005',
   'forged|attacker','independent-bank-confirmation',
   'Synthetic independent confirmation for maker-checker test')
  RETURNING verifier_subject")
[[ "$verifier_actor" == "https://idp.customer.example/tenant-a|human-verifier-0144" ]] || {
  echo "FAIL: database did not replace forged verifier identity: $verifier_actor" >&2; exit 1;
}

echo "[Gate 0.5.14.5] Human audit actor is database-derived"
audit_actor=$(actor pwr_gate0144_operator -Atc "
  INSERT INTO revenue_assurance.audit_events
  (tenant_id,business_unit_id,event_id,request_id,actor_subject,action,entity_type,entity_id)
  VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
   'a1000000-0000-4000-8000-000000000001',
   'f5300000-0000-4000-8000-000000000005',
   'gate-0.5.14.5-human-audit','forged|attacker',
   'recovery.test','recovery_outcome','f5100000-0000-4000-8000-000000000005')
  RETURNING actor_subject")
[[ "$audit_actor" == "https://idp.customer.example/tenant-a|human-operator-0144" ]] || {
  echo "FAIL: database did not replace forged human audit actor: $audit_actor" >&2; exit 1;
}

echo "[Gate 0.5.14.5] Verifier cannot record and maker cannot verify"
if actor pwr_gate0144_verifier -c "
  INSERT INTO revenue_assurance.recovery_outcomes
  (tenant_id,business_unit_id,outcome_id,case_id,amount,currency,outcome,evidence_reference,recorded_by)
  VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
   'a1000000-0000-4000-8000-000000000001',
   'f5400000-0000-4000-8000-000000000005',
   'f5000000-0000-4000-8000-000000000005',
   2000.0000,'NGN','reported','wrong-role-maker','forged')
" >/tmp/powerops-gate0145-verifier-maker.out 2>&1; then
  echo "FAIL: verifier role recorded a recovery outcome" >&2; exit 1
fi

if actor pwr_gate0144_operator -c "
  INSERT INTO revenue_assurance.recovery_verifications
  (tenant_id,business_unit_id,verification_id,outcome_id,verifier_subject,evidence_reference,reason)
  VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
   'a1000000-0000-4000-8000-000000000001',
   'f5500000-0000-4000-8000-000000000005',
   'f5100000-0000-4000-8000-000000000005',
   'forged','wrong-role-verification',
   'Maker must not perform finance verification')
" >/tmp/powerops-gate0145-maker-verifier.out 2>&1; then
  echo "FAIL: maker role verified a recovery outcome" >&2; exit 1
fi

echo "[Gate 0.5.14.5] Shared BU service login cannot bypass human actor mapping"
if actor pwr_gate1e_bu_a1 -c "
  INSERT INTO revenue_assurance.recovery_outcomes
  (tenant_id,business_unit_id,outcome_id,case_id,amount,currency,outcome,evidence_reference,recorded_by)
  VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
   'a1000000-0000-4000-8000-000000000001',
   'f5600000-0000-4000-8000-000000000005',
   'f5000000-0000-4000-8000-000000000005',
   3000.0000,'NGN','reported','shared-login-attempt','forged')
" >/tmp/powerops-gate0145-shared-login.out 2>&1; then
  echo "FAIL: shared BU service login wrote a human recovery outcome" >&2; exit 1
fi

echo "[Gate 0.5.14.5] PASS — recovery maker, verifier and human audit actors are DB-derived"
