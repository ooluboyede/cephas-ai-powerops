-- PowerOps Gate 1J — fence CREATEROLE membership on upgraded clusters.
-- Apply as the cluster migration administrator after 0003_scope_login_lifecycle.sql.
-- This replaces only the provisioning function; existing role bindings remain intact.
BEGIN;

CREATE OR REPLACE FUNCTION powerops_security.provision_scope_login(
    p_role_name name,
    p_tenant_id uuid,
    p_scope_kind text,
    p_business_unit_id uuid
)
RETURNS oid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_cluster_id uuid;
    v_role_oid oid;
    v_role pg_catalog.pg_roles%ROWTYPE;
BEGIN
    -- The function owner is powerops_provisioner. Only the controlled
    -- deployment authority should be granted EXECUTE on this function.
    IF p_role_name IS NULL
       OR length(p_role_name::text) > 63
       OR p_role_name::text !~ '^pwr_[a-z0-9_]{1,40}$' THEN
        RAISE EXCEPTION 'runtime role name is outside the approved format'
            USING ERRCODE = '22023';
    END IF;
    IF p_tenant_id IS NULL
       OR p_scope_kind NOT IN ('tenant', 'business_unit')
       OR (p_scope_kind = 'tenant' AND p_business_unit_id IS NOT NULL)
       OR (p_scope_kind = 'business_unit' AND p_business_unit_id IS NULL) THEN
        RAISE EXCEPTION 'invalid tenant/business-unit scope tuple'
            USING ERRCODE = '22023';
    END IF;

    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci
     WHERE ci.singleton
     FOR UPDATE;

    IF EXISTS (
        SELECT 1 FROM powerops_security.retired_role_identity AS retired
         WHERE retired.cluster_id = v_cluster_id
           AND retired.role_name = p_role_name
    ) THEN
        RAISE EXCEPTION 'runtime role name is permanently retired'
            USING ERRCODE = '23505';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = p_role_name
    ) THEN
        RAISE EXCEPTION 'runtime role name already exists; reuse is prohibited'
            USING ERRCODE = '23505';
    END IF;
    IF EXISTS (
        SELECT 1 FROM powerops_security.role_scope_binding AS binding
         WHERE binding.cluster_id = v_cluster_id
           AND binding.role_name = p_role_name
    ) THEN
        RAISE EXCEPTION 'runtime role name already has a scope binding'
            USING ERRCODE = '23505';
    END IF;

    -- Start NOLOGIN. The role becomes login-capable only after binding and
    -- least-privilege grants have been created and checked in this transaction.
    EXECUTE pg_catalog.format(
        'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
        p_role_name
    );

    -- PostgreSQL 16+ can grant the creating CREATEROLE principal membership
    -- in the newly created role. Remove it before the runtime identity is usable.
    EXECUTE pg_catalog.format(
        'REVOKE %I FROM powerops_provisioner', p_role_name
    );

    SELECT r.oid INTO STRICT v_role_oid
      FROM pg_catalog.pg_roles AS r
     WHERE r.rolname = p_role_name;

    IF EXISTS (
        SELECT 1 FROM powerops_security.retired_role_identity AS retired
         WHERE retired.cluster_id = v_cluster_id
           AND retired.role_oid = v_role_oid
    ) THEN
        RAISE EXCEPTION 'PostgreSQL reused a retired role OID; provisioning denied'
            USING ERRCODE = '23505';
    END IF;

    INSERT INTO powerops_security.role_scope_binding (
        cluster_id, role_oid, role_name, tenant_id,
        scope_kind, business_unit_id, active
    ) VALUES (
        v_cluster_id, v_role_oid, p_role_name, p_tenant_id,
        p_scope_kind, p_business_unit_id, false
    );

    EXECUTE pg_catalog.format(
        'GRANT USAGE ON SCHEMA powerops_security TO %I', p_role_name
    );
    EXECUTE pg_catalog.format(
        'GRANT EXECUTE ON FUNCTION powerops_security.resolve_authenticated_scope() TO %I',
        p_role_name
    );

    SELECT * INTO STRICT v_role
      FROM pg_catalog.pg_roles
     WHERE oid = v_role_oid;

    IF v_role.rolcanlogin OR v_role.rolsuper OR v_role.rolcreatedb
       OR v_role.rolcreaterole OR v_role.rolinherit
       OR v_role.rolreplication OR v_role.rolbypassrls THEN
        RAISE EXCEPTION 'runtime role privilege verification failed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members AS m
         WHERE m.member = v_role_oid OR m.roleid = v_role_oid
    ) THEN
        RAISE EXCEPTION 'runtime role unexpectedly has role memberships';
    END IF;

    UPDATE powerops_security.role_scope_binding
       SET active = true
     WHERE cluster_id = v_cluster_id AND role_oid = v_role_oid
       AND NOT active;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'scope binding activation failed';
    END IF;

    -- LOGIN is the final state transition. The transaction commits atomically.
    EXECUTE pg_catalog.format('ALTER ROLE %I LOGIN', p_role_name);
    RETURN v_role_oid;
END
$function$;

ALTER FUNCTION powerops_security.provision_scope_login(name, uuid, text, uuid)
    OWNER TO powerops_provisioner;
REVOKE ALL ON FUNCTION powerops_security.provision_scope_login(name, uuid, text, uuid)
    FROM PUBLIC;


ALTER FUNCTION powerops_security.provision_scope_login(name, uuid, text, uuid)
    OWNER TO powerops_provisioner;
REVOKE ALL ON FUNCTION powerops_security.provision_scope_login(name, uuid, text, uuid)
    FROM PUBLIC;

COMMIT;
