-- Gate 0.5.14.5: derive finance maker, verifier and human audit actors in PostgreSQL.
BEGIN;

CREATE OR REPLACE FUNCTION revenue_assurance.bind_recovery_outcome_to_human_maker()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, revenue_assurance, powerops_security
AS $function$
DECLARE
    v_actor record;
BEGIN
    SELECT * INTO STRICT v_actor
      FROM powerops_security.resolve_authenticated_human_actor_v2();

    IF v_actor.finance_operator IS NOT TRUE
       OR v_actor.finance_verifier IS TRUE THEN
        RAISE EXCEPTION 'only a database-authenticated finance maker may record recovery outcomes'
            USING ERRCODE = '42501';
    END IF;

    -- Never trust the API or caller's INSERT value for the maker identity.
    NEW.recorded_by := v_actor.actor_subject;
    RETURN NEW;
END
$function$;

CREATE OR REPLACE FUNCTION revenue_assurance.bind_recovery_verification_to_human_verifier()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, revenue_assurance, powerops_security
AS $function$
DECLARE
    v_actor record;
    v_recorded_by text;
BEGIN
    SELECT * INTO STRICT v_actor
      FROM powerops_security.resolve_authenticated_human_actor_v2();

    IF v_actor.finance_verifier IS NOT TRUE
       OR v_actor.finance_operator IS TRUE THEN
        RAISE EXCEPTION 'only a database-authenticated finance verifier may verify recovery outcomes'
            USING ERRCODE = '42501';
    END IF;

    SELECT outcome.recorded_by INTO STRICT v_recorded_by
      FROM revenue_assurance.recovery_outcomes AS outcome
     WHERE outcome.tenant_id = NEW.tenant_id
       AND outcome.business_unit_id = NEW.business_unit_id
       AND outcome.outcome_id = NEW.outcome_id
     FOR SHARE;

    IF v_recorded_by = v_actor.actor_subject THEN
        RAISE EXCEPTION 'recovery outcome maker cannot verify the same outcome'
            USING ERRCODE = '42501';
    END IF;

    -- The verifier identity is database-derived; a supplied value is ignored.
    NEW.verifier_subject := v_actor.actor_subject;
    RETURN NEW;
END
$function$;

CREATE OR REPLACE FUNCTION revenue_assurance.bind_human_audit_actor()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, revenue_assurance, powerops_security
AS $function$
DECLARE
    v_cluster_id uuid;
    v_session_role_oid oid;
    v_actor_subject text;
BEGIN
    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci
     WHERE ci.singleton;

    SELECT role.oid INTO v_session_role_oid
      FROM pg_catalog.pg_roles AS role
     WHERE role.rolname = session_user;

    -- Preserve legacy service-role audit behavior only when this login has no
    -- human actor mapping at all. Inactive/expired mappings still fail closed
    -- because their role OID remains in the protected registry.
    IF EXISTS (
        SELECT 1
          FROM powerops_security.human_actor_binding AS binding
         WHERE binding.cluster_id = v_cluster_id
           AND binding.role_oid = v_session_role_oid
    ) THEN
        SELECT actor.actor_subject INTO STRICT v_actor_subject
          FROM powerops_security.resolve_authenticated_human_actor_v2() AS actor;
        NEW.actor_subject := v_actor_subject;
    END IF;

    RETURN NEW;
END
$function$;

ALTER FUNCTION revenue_assurance.bind_human_audit_actor()
    OWNER TO powerops_scope_resolver;

REVOKE ALL ON FUNCTION revenue_assurance.bind_recovery_outcome_to_human_maker()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION revenue_assurance.bind_recovery_verification_to_human_verifier()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION revenue_assurance.bind_human_audit_actor()
    FROM PUBLIC;

-- Alphabetical trigger order ensures the database-derived verifier is assigned
-- before the pre-existing maker-checker trigger compares verifier_subject.
CREATE TRIGGER a10_recovery_outcome_human_maker
    BEFORE INSERT ON revenue_assurance.recovery_outcomes
    FOR EACH ROW
    EXECUTE FUNCTION revenue_assurance.bind_recovery_outcome_to_human_maker();

CREATE TRIGGER a10_recovery_verification_human_verifier
    BEFORE INSERT ON revenue_assurance.recovery_verifications
    FOR EACH ROW
    EXECUTE FUNCTION revenue_assurance.bind_recovery_verification_to_human_verifier();

CREATE TRIGGER a10_human_audit_actor
    BEFORE INSERT ON revenue_assurance.audit_events
    FOR EACH ROW
    EXECUTE FUNCTION revenue_assurance.bind_human_audit_actor();

COMMIT;
