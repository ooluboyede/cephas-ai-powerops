-- Gate 0.5.14.1: protected human actor identity foundation.
BEGIN;

CREATE TABLE powerops_security.human_actor_binding (
    cluster_id uuid NOT NULL,
    role_oid oid NOT NULL,
    issuer text NOT NULL CHECK (length(btrim(issuer)) BETWEEN 9 AND 500 AND issuer ~ '^https://'),
    subject text NOT NULL CHECK (length(btrim(subject)) BETWEEN 1 AND 200),
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    finance_verifier boolean NOT NULL DEFAULT false,
    active boolean NOT NULL DEFAULT true,
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    created_by name NOT NULL DEFAULT session_user,
    revoked_at timestamptz,
    revoked_by name,
    revocation_reason text,
    PRIMARY KEY (cluster_id, role_oid),
    UNIQUE (cluster_id, issuer, subject, tenant_id, business_unit_id),
    FOREIGN KEY (cluster_id, role_oid)
        REFERENCES powerops_security.role_scope_binding(cluster_id, role_oid),
    CHECK (expires_at IS NULL OR expires_at > created_at),
    CHECK (
      (active AND revoked_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL)
      OR
      (NOT active AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL
       AND revocation_reason IS NOT NULL)
    )
);
ALTER TABLE powerops_security.human_actor_binding OWNER TO powerops_provisioner;
REVOKE ALL ON powerops_security.human_actor_binding FROM PUBLIC;
REVOKE ALL ON powerops_security.human_actor_binding FROM powerops_provisioner;
GRANT SELECT, INSERT, UPDATE ON powerops_security.human_actor_binding TO powerops_provisioner;
GRANT SELECT ON powerops_security.human_actor_binding TO powerops_scope_resolver;

CREATE OR REPLACE FUNCTION powerops_security.provision_human_actor_login(
    p_role_name name, p_tenant_id uuid, p_business_unit_id uuid,
    p_issuer text, p_subject text, p_finance_verifier boolean DEFAULT false,
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
    IF p_issuer IS NULL OR length(btrim(p_issuer)) NOT BETWEEN 9 AND 500
       OR p_issuer !~ '^https://'
       OR p_subject IS NULL OR length(btrim(p_subject)) NOT BETWEEN 1 AND 200
       OR p_tenant_id IS NULL OR p_business_unit_id IS NULL
       OR (p_expires_at IS NOT NULL AND p_expires_at <= pg_catalog.clock_timestamp()) THEN
        RAISE EXCEPTION 'invalid human actor identity provisioning request'
            USING ERRCODE = '22023';
    END IF;
    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci WHERE ci.singleton;

    v_role_oid := powerops_security.provision_scope_login(
        p_role_name, p_tenant_id, 'business_unit', p_business_unit_id
    );
    INSERT INTO powerops_security.human_actor_binding (
        cluster_id, role_oid, issuer, subject, tenant_id, business_unit_id,
        finance_verifier, active, expires_at
    ) VALUES (
        v_cluster_id, v_role_oid, p_issuer, p_subject, p_tenant_id,
        p_business_unit_id, COALESCE(p_finance_verifier, false), true, p_expires_at
    );
    EXECUTE pg_catalog.format(
        'GRANT EXECUTE ON FUNCTION powerops_security.resolve_authenticated_human_actor() TO %I',
        p_role_name
    );
    RETURN v_role_oid;
END
$function$;

CREATE OR REPLACE FUNCTION powerops_security.resolve_authenticated_human_actor()
RETURNS TABLE (
    cluster_id uuid, tenant_id uuid, business_unit_id uuid,
    authenticated_role_oid oid, actor_subject text, finance_verifier boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_scope record;
    v_actor powerops_security.human_actor_binding%ROWTYPE;
BEGIN
    -- resolve_authenticated_scope derives the role OID from session_user.
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

    RETURN QUERY SELECT v_actor.cluster_id, v_actor.tenant_id,
        v_actor.business_unit_id, v_actor.role_oid,
        v_actor.issuer || '|' || v_actor.subject, v_actor.finance_verifier;
EXCEPTION
    WHEN NO_DATA_FOUND OR TOO_MANY_ROWS THEN
        RAISE EXCEPTION 'authenticated database identity has no unique active human actor mapping'
            USING ERRCODE = '42501';
END
$function$;

CREATE OR REPLACE FUNCTION powerops_security.revoke_human_actor_login(
    p_role_name name, p_revocation_reason text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_cluster_id uuid;
    v_role_oid oid;
BEGIN
    IF p_role_name IS NULL OR p_revocation_reason IS NULL
       OR length(btrim(p_revocation_reason)) < 8
       OR length(p_revocation_reason) > 500 THEN
        RAISE EXCEPTION 'invalid human actor revocation request'
            USING ERRCODE = '22023';
    END IF;
    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci WHERE ci.singleton;
    SELECT binding.role_oid INTO STRICT v_role_oid
      FROM powerops_security.human_actor_binding AS binding
      JOIN pg_catalog.pg_roles AS runtime_role
        ON runtime_role.oid = binding.role_oid AND runtime_role.rolname = p_role_name
     WHERE binding.cluster_id = v_cluster_id AND binding.active
     FOR UPDATE;

    UPDATE powerops_security.human_actor_binding
       SET active = false, revoked_at = pg_catalog.clock_timestamp(),
           revoked_by = session_user, revocation_reason = p_revocation_reason
     WHERE cluster_id = v_cluster_id AND role_oid = v_role_oid;
    PERFORM powerops_security.retire_scope_login(p_role_name, p_revocation_reason);
END
$function$;

ALTER FUNCTION powerops_security.resolve_authenticated_human_actor()
    OWNER TO powerops_scope_resolver;
ALTER FUNCTION powerops_security.provision_human_actor_login(
    name, uuid, uuid, text, text, boolean, timestamptz
) OWNER TO powerops_provisioner;
ALTER FUNCTION powerops_security.revoke_human_actor_login(name, text)
    OWNER TO powerops_provisioner;

REVOKE ALL ON FUNCTION powerops_security.resolve_authenticated_human_actor() FROM PUBLIC;
REVOKE ALL ON FUNCTION powerops_security.provision_human_actor_login(
    name, uuid, uuid, text, text, boolean, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION powerops_security.revoke_human_actor_login(name, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.provision_human_actor_login(
    name, uuid, uuid, text, text, boolean, timestamptz
) TO powerops_provisioner;
GRANT EXECUTE ON FUNCTION powerops_security.revoke_human_actor_login(name, text)
    TO powerops_provisioner;

COMMIT;
