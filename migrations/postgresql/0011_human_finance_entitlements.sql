-- Gate 0.5.14.4: distinct database-enforced finance maker/verifier entitlements.
BEGIN;

ALTER TABLE powerops_security.human_actor_binding
    ADD COLUMN finance_operator boolean NOT NULL DEFAULT false;

ALTER TABLE powerops_security.human_actor_binding
    ADD CONSTRAINT human_actor_binding_finance_entitlement_exclusive
    CHECK (NOT (finance_operator AND finance_verifier));

CREATE OR REPLACE FUNCTION powerops_security.provision_human_actor_login_v2(
    p_role_name name,
    p_tenant_id uuid,
    p_business_unit_id uuid,
    p_issuer text,
    p_subject text,
    p_finance_operator boolean DEFAULT false,
    p_finance_verifier boolean DEFAULT false,
    p_expires_at timestamptz DEFAULT NULL
)
RETURNS oid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_cluster_id uuid;
    v_role_oid oid;
BEGIN
    IF COALESCE(p_finance_operator, false)
       AND COALESCE(p_finance_verifier, false) THEN
        RAISE EXCEPTION 'human actor cannot hold both finance maker and verifier entitlements'
            USING ERRCODE = '22023';
    END IF;

    v_role_oid := powerops_security.provision_human_actor_login(
        p_role_name,
        p_tenant_id,
        p_business_unit_id,
        p_issuer,
        p_subject,
        COALESCE(p_finance_verifier, false),
        p_expires_at
    );

    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci
     WHERE ci.singleton;

    UPDATE powerops_security.human_actor_binding
       SET finance_operator = COALESCE(p_finance_operator, false)
     WHERE cluster_id = v_cluster_id
       AND role_oid = v_role_oid;

    EXECUTE pg_catalog.format(
        'GRANT EXECUTE ON FUNCTION powerops_security.resolve_authenticated_human_actor_v2() TO %I',
        p_role_name
    );

    RETURN v_role_oid;
END
$function$;

CREATE OR REPLACE FUNCTION powerops_security.resolve_authenticated_human_actor_v2()
RETURNS TABLE (
    cluster_id uuid,
    tenant_id uuid,
    business_unit_id uuid,
    authenticated_role_oid oid,
    actor_subject text,
    finance_operator boolean,
    finance_verifier boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_scope record;
    v_actor powerops_security.human_actor_binding%ROWTYPE;
BEGIN
    SELECT * INTO STRICT v_scope
      FROM powerops_security.resolve_authenticated_scope();

    SELECT binding.* INTO STRICT v_actor
      FROM powerops_security.human_actor_binding AS binding
     WHERE binding.cluster_id = v_scope.cluster_id
       AND binding.role_oid = v_scope.authenticated_role_oid
       AND binding.tenant_id = v_scope.tenant_id
       AND binding.business_unit_id = v_scope.business_unit_id
       AND binding.active
       AND (binding.expires_at IS NULL
            OR binding.expires_at > pg_catalog.clock_timestamp());

    RETURN QUERY SELECT
        v_actor.cluster_id,
        v_actor.tenant_id,
        v_actor.business_unit_id,
        v_actor.role_oid,
        v_actor.issuer || '|' || v_actor.subject,
        v_actor.finance_operator,
        v_actor.finance_verifier;
EXCEPTION
    WHEN NO_DATA_FOUND OR TOO_MANY_ROWS THEN
        RAISE EXCEPTION 'authenticated database identity has no unique active human actor mapping'
            USING ERRCODE = '42501';
END
$function$;

ALTER FUNCTION powerops_security.provision_human_actor_login_v2(
    name, uuid, uuid, text, text, boolean, boolean, timestamptz
) OWNER TO powerops_provisioner;
ALTER FUNCTION powerops_security.resolve_authenticated_human_actor_v2()
    OWNER TO powerops_scope_resolver;

REVOKE ALL ON FUNCTION powerops_security.provision_human_actor_login_v2(
    name, uuid, uuid, text, text, boolean, boolean, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.provision_human_actor_login_v2(
    name, uuid, uuid, text, text, boolean, boolean, timestamptz
) TO powerops_provisioner;

REVOKE ALL ON FUNCTION powerops_security.resolve_authenticated_human_actor_v2()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.resolve_authenticated_human_actor_v2()
    TO powerops_provisioner WITH GRANT OPTION;

COMMIT;
