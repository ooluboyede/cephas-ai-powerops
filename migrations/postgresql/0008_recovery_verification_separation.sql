-- Gate 0.5.6: recovery verification is a separate immutable, maker-checker event.
BEGIN;

CREATE TABLE revenue_assurance.recovery_verifications (
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    verification_id uuid NOT NULL,
    outcome_id uuid NOT NULL,
    verifier_subject text NOT NULL
        CHECK (length(btrim(verifier_subject)) BETWEEN 1 AND 200),
    evidence_reference text NOT NULL
        CHECK (length(btrim(evidence_reference)) BETWEEN 3 AND 240),
    reason text NOT NULL
        CHECK (length(btrim(reason)) BETWEEN 10 AND 2000),
    verified_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, business_unit_id, verification_id),
    UNIQUE (tenant_id, business_unit_id, outcome_id),
    FOREIGN KEY (tenant_id, business_unit_id, outcome_id)
        REFERENCES revenue_assurance.recovery_outcomes
            (tenant_id, business_unit_id, outcome_id),
    FOREIGN KEY (tenant_id, business_unit_id)
        REFERENCES powerops_data.business_units (tenant_id, business_unit_id)
);

ALTER TABLE revenue_assurance.recovery_verifications
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE revenue_assurance.recovery_verifications
    FORCE ROW LEVEL SECURITY;
CREATE POLICY recovery_verifications_scope_policy
    ON revenue_assurance.recovery_verifications
    FOR ALL
    USING (powerops_security.row_scope_permits(tenant_id, business_unit_id))
    WITH CHECK (powerops_security.row_scope_permits(tenant_id, business_unit_id));

-- Defence in depth: even a direct INSERT cannot self-verify or verify an
-- outcome that was not recorded as a reportable recovery assertion.
CREATE OR REPLACE FUNCTION revenue_assurance.enforce_recovery_verifier_separation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, revenue_assurance
AS $function$
DECLARE
    v_recorded_by text;
BEGIN
    SELECT outcome.recorded_by INTO v_recorded_by
      FROM revenue_assurance.recovery_outcomes AS outcome
     WHERE outcome.tenant_id = NEW.tenant_id
       AND outcome.business_unit_id = NEW.business_unit_id
       AND outcome.outcome_id = NEW.outcome_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'recovery outcome does not exist in the requested scope'
            USING ERRCODE = '23503';
    END IF;

    IF NEW.verifier_subject = v_recorded_by THEN
        RAISE EXCEPTION 'recovery outcome recorder cannot verify the same outcome'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END
$function$;

REVOKE ALL ON FUNCTION revenue_assurance.enforce_recovery_verifier_separation()
    FROM PUBLIC;
CREATE TRIGGER recovery_verifications_distinct_actor
    BEFORE INSERT ON revenue_assurance.recovery_verifications
    FOR EACH ROW
    EXECUTE FUNCTION revenue_assurance.enforce_recovery_verifier_separation();

CREATE TRIGGER recovery_verifications_no_mutation
    BEFORE UPDATE OR DELETE ON revenue_assurance.recovery_verifications
    FOR EACH ROW
    EXECUTE FUNCTION revenue_assurance.reject_audit_mutation();

-- Prevent clients from asserting "verified" at the recording stage. Verification
-- exists only as a separate row in recovery_verifications.
CREATE OR REPLACE FUNCTION revenue_assurance.reject_direct_verified_outcome()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, revenue_assurance
AS $function$
BEGIN
    IF NEW.outcome = 'verified' THEN
        RAISE EXCEPTION 'recovery outcomes must be verified through the separate verification workflow'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END
$function$;

REVOKE ALL ON FUNCTION revenue_assurance.reject_direct_verified_outcome()
    FROM PUBLIC;
CREATE TRIGGER recovery_outcomes_no_direct_verified
    BEFORE INSERT OR UPDATE OF outcome ON revenue_assurance.recovery_outcomes
    FOR EACH ROW
    EXECUTE FUNCTION revenue_assurance.reject_direct_verified_outcome();

GRANT SELECT, INSERT ON revenue_assurance.recovery_verifications
    TO powerops_provisioner WITH GRANT OPTION;

COMMIT;
