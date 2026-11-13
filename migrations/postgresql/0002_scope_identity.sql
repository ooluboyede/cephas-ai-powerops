-- PowerOps 0.1.1 Gate 1A — authenticated database identity to explicit scope.
-- Apply as the controlled migration authority after 0001_bootstrap_roles.sql.
-- Requires PostgreSQL 14+; verify exact customer build before deployment.
BEGIN;

CREATE SCHEMA IF NOT EXISTS powerops_security AUTHORIZATION powerops_provisioner;
ALTER SCHEMA powerops_security OWNER TO powerops_provisioner;
REVOKE ALL ON SCHEMA powerops_security FROM PUBLIC;

CREATE TABLE IF NOT EXISTS powerops_security.cluster_identity (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    cluster_id uuid NOT NULL UNIQUE,
    provisioned_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    provisioned_by name NOT NULL DEFAULT session_user
);
ALTER TABLE powerops_security.cluster_identity OWNER TO powerops_provisioner;

-- Exactly one explicit security scope per login role OID in this cluster.
CREATE TABLE IF NOT EXISTS powerops_security.role_scope_binding (
    cluster_id uuid NOT NULL,
    role_oid oid NOT NULL,
    role_name name NOT NULL,
    tenant_id uuid NOT NULL,
    scope_kind text NOT NULL CHECK (scope_kind IN ('tenant', 'business_unit')),
    business_unit_id uuid,
    active boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    created_by name NOT NULL DEFAULT session_user,
    PRIMARY KEY (cluster_id, role_oid),
    UNIQUE (cluster_id, role_name),
    CHECK (
        (scope_kind = 'tenant' AND business_unit_id IS NULL)
        OR
        (scope_kind = 'business_unit' AND business_unit_id IS NOT NULL)
    )
);
ALTER TABLE powerops_security.role_scope_binding OWNER TO powerops_provisioner;

-- Permanent retired identity tombstones. Normal provisioning must never delete these.
CREATE TABLE IF NOT EXISTS powerops_security.retired_role_identity (
    cluster_id uuid NOT NULL,
    role_oid oid NOT NULL,
    role_name name NOT NULL,
    retired_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    retired_by name NOT NULL DEFAULT session_user,
    retirement_reason text NOT NULL,
    PRIMARY KEY (cluster_id, role_oid),
    UNIQUE (cluster_id, role_name)
);
ALTER TABLE powerops_security.retired_role_identity OWNER TO powerops_provisioner;

REVOKE ALL ON ALL TABLES IN SCHEMA powerops_security FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA powerops_security FROM powerops_scope_resolver;
GRANT USAGE ON SCHEMA powerops_security TO powerops_scope_resolver;
GRANT SELECT ON powerops_security.cluster_identity,
                powerops_security.role_scope_binding,
                powerops_security.retired_role_identity
TO powerops_scope_resolver;

-- SECURITY DEFINER owner has SELECT only. It does not own application tables,
-- cannot manage roles, and cannot mutate identity mappings or tombstones.
CREATE OR REPLACE FUNCTION powerops_security.resolve_authenticated_scope()
RETURNS TABLE (
    cluster_id uuid,
    tenant_id uuid,
    scope_kind text,
    business_unit_id uuid,
    authenticated_role_oid oid
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_cluster_id uuid;
    v_role_oid oid;
    v_role_name name;
    v_binding powerops_security.role_scope_binding%ROWTYPE;
    v_retired boolean;
BEGIN
    -- session_user is the authenticated login, even inside SECURITY DEFINER.
    -- Resolve it through the trusted PostgreSQL role catalog; never accept a
    -- caller-supplied name, OID, tenant, BU, JWT claim, SQL argument or GUC.
    v_role_name := session_user;
    SELECT r.oid
      INTO STRICT v_role_oid
      FROM pg_catalog.pg_roles AS r
     WHERE r.rolname = session_user
       AND r.rolcanlogin;

    SELECT ci.cluster_id
      INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci
     WHERE ci.singleton;

    SELECT EXISTS (
        SELECT 1
          FROM powerops_security.retired_role_identity AS retired
         WHERE retired.cluster_id = v_cluster_id
           AND (retired.role_oid = v_role_oid OR retired.role_name = v_role_name)
    ) INTO v_retired;

    IF v_retired THEN
        RAISE EXCEPTION 'authenticated database identity is retired'
            USING ERRCODE = '42501';
    END IF;

    SELECT binding.*
      INTO STRICT v_binding
      FROM powerops_security.role_scope_binding AS binding
     WHERE binding.cluster_id = v_cluster_id
       AND binding.role_oid = v_role_oid
       AND binding.role_name = v_role_name
       AND binding.active;

    RETURN QUERY SELECT
        v_cluster_id,
        v_binding.tenant_id,
        v_binding.scope_kind,
        v_binding.business_unit_id,
        v_role_oid;
EXCEPTION
    WHEN NO_DATA_FOUND OR TOO_MANY_ROWS THEN
        RAISE EXCEPTION 'authenticated database identity has no unique active scope'
            USING ERRCODE = '42501';
END
$function$;

ALTER FUNCTION powerops_security.resolve_authenticated_scope()
    OWNER TO powerops_scope_resolver;
REVOKE ALL ON FUNCTION powerops_security.resolve_authenticated_scope() FROM PUBLIC;

-- No runtime role is granted access here. Provisioning must explicitly grant
-- USAGE on the schema and EXECUTE on this function to each approved scope login.
COMMIT;
