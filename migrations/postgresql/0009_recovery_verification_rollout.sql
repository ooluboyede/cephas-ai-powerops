-- Gate 0.5.8: safe rollout of recovery verification to existing deployments.
BEGIN;

-- Do not silently discard or invent verification evidence for legacy rows.
-- Existing verified rows must be reconciled by the customer before this migration.
DO $preflight$
DECLARE
    v_legacy_count bigint;
BEGIN
    SELECT count(*) INTO v_legacy_count
      FROM revenue_assurance.recovery_outcomes
     WHERE outcome = 'verified';

    IF v_legacy_count > 0 THEN
        RAISE EXCEPTION
            'Gate 0.5.8 blocked: % legacy verified recovery outcome(s) require customer reconciliation before migration. No verifier evidence was fabricated.',
            v_legacy_count
            USING ERRCODE = '55000';
    END IF;
END
$preflight$;

-- Existing BU-scoped runtime roles are not automatically granted privileges
-- on a table created after their initial provisioning. Reuse the hardened
-- provisioning function, which validates active DB-bound BU identities and
-- rejects tenant-wide, retired, privileged, or unsafe role memberships.
DO $grant_existing_roles$
DECLARE
    v_role_name name;
BEGIN
    FOR v_role_name IN
        SELECT binding.role_name
          FROM powerops_security.role_scope_binding AS binding
         WHERE binding.active
           AND binding.scope_kind = 'business_unit'
           AND binding.business_unit_id IS NOT NULL
         ORDER BY binding.role_name
    LOOP
        PERFORM powerops_security.grant_revenue_assurance_access(v_role_name);
    END LOOP;
END
$grant_existing_roles$;

COMMIT;
