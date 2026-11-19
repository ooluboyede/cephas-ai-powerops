-- Gate 0.5.14.8.6 PS-02.1.1: exact human-session admission registry.
-- Apply as a customer PostgreSQL administrator after migrations 0010-0012.
-- The control role is NOLOGIN; application and human roles never receive
-- direct registry-table privileges or backend-signal privileges.
BEGIN;

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'powerops_provisioner')
       OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'powerops_scope_resolver') THEN
        RAISE EXCEPTION 'required PowerOps provisioner/scope-resolver roles are missing';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'powerops_session_control') THEN
        CREATE ROLE powerops_session_control
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT
            NOREPLICATION NOBYPASSRLS;
    END IF;
END
$roles$;

-- PostgreSQL exposes these cluster-wide capabilities through predefined roles.
-- The holder is a dedicated NOLOGIN function owner, never an application login.
GRANT pg_signal_backend TO powerops_session_control;
GRANT pg_read_all_stats TO powerops_session_control;
GRANT CREATE ON SCHEMA powerops_security TO powerops_session_control;
GRANT SELECT ON powerops_security.cluster_identity TO powerops_session_control;
GRANT SELECT ON powerops_security.role_scope_binding TO powerops_session_control;
GRANT SELECT ON powerops_security.human_actor_binding TO powerops_session_control;

CREATE TABLE powerops_security.human_database_session_binding (
    session_id uuid PRIMARY KEY,
    cluster_id uuid NOT NULL,
    role_oid oid NOT NULL,
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    issuer text NOT NULL,
    subject text NOT NULL,
    expires_at timestamptz NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    created_by name NOT NULL DEFAULT session_user,
    revoked_at timestamptz,
    revoked_by name,
    CHECK (expires_at > created_at),
    CHECK (
      (active AND revoked_at IS NULL AND revoked_by IS NULL)
      OR
      (NOT active AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL)
    ),
    FOREIGN KEY (cluster_id, role_oid)
      REFERENCES powerops_security.human_actor_binding(cluster_id, role_oid)
);

CREATE INDEX human_database_session_binding_active_role_idx
    ON powerops_security.human_database_session_binding(cluster_id, role_oid)
    WHERE active;

CREATE TABLE powerops_security.human_database_session_backend (
    session_id uuid NOT NULL
      REFERENCES powerops_security.human_database_session_binding(session_id),
    backend_pid integer NOT NULL CHECK (backend_pid > 0),
    backend_start timestamptz NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    terminated_at timestamptz,
    PRIMARY KEY (session_id, backend_pid, backend_start)
);

CREATE INDEX human_database_session_backend_live_idx
    ON powerops_security.human_database_session_backend(session_id)
    WHERE terminated_at IS NULL;

ALTER TABLE powerops_security.human_database_session_binding
    OWNER TO powerops_session_control;
ALTER TABLE powerops_security.human_database_session_backend
    OWNER TO powerops_session_control;
REVOKE ALL ON powerops_security.human_database_session_binding FROM PUBLIC;
REVOKE ALL ON powerops_security.human_database_session_backend FROM PUBLIC;
REVOKE ALL ON powerops_security.human_database_session_binding
    FROM powerops_provisioner, powerops_scope_resolver;
REVOKE ALL ON powerops_security.human_database_session_backend
    FROM powerops_provisioner, powerops_scope_resolver;

-- Provision only from an already provisioned, active human actor login.
-- Tenant, BU, issuer and subject are derived from the protected actor row.
CREATE OR REPLACE FUNCTION powerops_security.provision_human_database_session(
    p_session_id uuid,
    p_role_name name,
    p_expires_at timestamptz
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_cluster_id uuid;
    v_role_oid oid;
    v_actor powerops_security.human_actor_binding%ROWTYPE;
    v_role pg_catalog.pg_roles%ROWTYPE;
BEGIN
    IF p_session_id IS NULL OR p_role_name IS NULL OR p_expires_at IS NULL
       OR p_expires_at <= pg_catalog.clock_timestamp()
       OR p_expires_at > pg_catalog.clock_timestamp() + interval '5 minutes' THEN
        RAISE EXCEPTION 'invalid human database session lease'
            USING ERRCODE = '22023';
    END IF;

    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci
     WHERE ci.singleton;

    SELECT role.oid INTO STRICT v_role_oid
      FROM pg_catalog.pg_roles AS role
     WHERE role.rolname = p_role_name;
    SELECT role.* INTO STRICT v_role
      FROM pg_catalog.pg_roles AS role
     WHERE role.oid = v_role_oid;

    IF NOT v_role.rolcanlogin OR v_role.rolsuper OR v_role.rolcreatedb
       OR v_role.rolcreaterole OR v_role.rolinherit
       OR v_role.rolreplication OR v_role.rolbypassrls THEN
        RAISE EXCEPTION 'database session role is not an approved human login'
            USING ERRCODE = '42501';
    END IF;

    SELECT actor.* INTO STRICT v_actor
      FROM powerops_security.human_actor_binding AS actor
      JOIN powerops_security.role_scope_binding AS scope_binding
        ON scope_binding.cluster_id = actor.cluster_id
       AND scope_binding.role_oid = actor.role_oid
     WHERE actor.cluster_id = v_cluster_id
       AND actor.role_oid = v_role_oid
       AND actor.active
       AND scope_binding.active
       AND (actor.expires_at IS NULL OR actor.expires_at > pg_catalog.clock_timestamp());

    IF p_expires_at > COALESCE(v_actor.expires_at, p_expires_at) THEN
        RAISE EXCEPTION 'session lease exceeds the human actor entitlement expiry'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO powerops_security.human_database_session_binding (
        session_id, cluster_id, role_oid, tenant_id, business_unit_id,
        issuer, subject, expires_at
    ) VALUES (
        p_session_id, v_cluster_id, v_role_oid, v_actor.tenant_id,
        v_actor.business_unit_id, v_actor.issuer, v_actor.subject, p_expires_at
    );

    EXECUTE pg_catalog.format(
        'GRANT EXECUTE ON FUNCTION powerops_security.register_human_database_session_backend(uuid) TO %I',
        p_role_name
    );
EXCEPTION
    WHEN unique_violation THEN
        RAISE EXCEPTION 'human database session identifier has already been used'
            USING ERRCODE = '23505';
END
$function$;

ALTER FUNCTION powerops_security.provision_human_database_session(uuid, name, timestamptz)
    OWNER TO powerops_session_control;
REVOKE ALL ON FUNCTION powerops_security.provision_human_database_session(uuid, name, timestamptz)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.provision_human_database_session(uuid, name, timestamptz)
    TO powerops_provisioner;

-- Must be called on the new physical connection before application SQL is run.
-- session_user, backend PID and backend_start are database-derived; no caller
-- identity or backend identifier is accepted by this function.
CREATE OR REPLACE FUNCTION powerops_security.register_human_database_session_backend(
    p_session_id uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_cluster_id uuid;
    v_role_oid oid;
    v_binding powerops_security.human_database_session_binding%ROWTYPE;
    v_backend_start timestamptz;
BEGIN
    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci
     WHERE ci.singleton;

    SELECT role.oid INTO STRICT v_role_oid
      FROM pg_catalog.pg_roles AS role
     WHERE role.rolname = session_user;

    -- FOR SHARE serializes admission with the revoker's UPDATE of this exact row.
    SELECT binding.* INTO STRICT v_binding
      FROM powerops_security.human_database_session_binding AS binding
     WHERE binding.session_id = p_session_id
       AND binding.cluster_id = v_cluster_id
       AND binding.role_oid = v_role_oid
       AND binding.active
       AND binding.expires_at > pg_catalog.clock_timestamp()
     FOR SHARE;

    PERFORM 1
      FROM powerops_security.human_actor_binding AS actor
      JOIN powerops_security.role_scope_binding AS scope_binding
        ON scope_binding.cluster_id = actor.cluster_id
       AND scope_binding.role_oid = actor.role_oid
     WHERE actor.cluster_id = v_binding.cluster_id
       AND actor.role_oid = v_binding.role_oid
       AND actor.active
       AND scope_binding.active
       AND actor.tenant_id = v_binding.tenant_id
       AND actor.business_unit_id = v_binding.business_unit_id
       AND actor.issuer = v_binding.issuer
       AND actor.subject = v_binding.subject
       AND (actor.expires_at IS NULL OR actor.expires_at > pg_catalog.clock_timestamp());
    IF NOT FOUND THEN
        RAISE EXCEPTION 'human actor entitlement is no longer active'
            USING ERRCODE = '42501';
    END IF;

    SELECT activity.backend_start INTO STRICT v_backend_start
      FROM pg_catalog.pg_stat_activity AS activity
     WHERE activity.pid = pg_catalog.pg_backend_pid();

    INSERT INTO powerops_security.human_database_session_backend (
        session_id, backend_pid, backend_start
    ) VALUES (
        p_session_id, pg_catalog.pg_backend_pid(), v_backend_start
    )
    ON CONFLICT (session_id, backend_pid, backend_start) DO NOTHING;

    RETURN true;
EXCEPTION
    WHEN NO_DATA_FOUND OR TOO_MANY_ROWS THEN
        RAISE EXCEPTION 'human database session is unknown, expired, revoked, or bound to another login'
            USING ERRCODE = '42501';
END
$function$;

ALTER FUNCTION powerops_security.register_human_database_session_backend(uuid)
    OWNER TO powerops_session_control;
REVOKE ALL ON FUNCTION powerops_security.register_human_database_session_backend(uuid)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.register_human_database_session_backend(uuid)
    TO powerops_provisioner;

-- The controller must call this using a dedicated control connection. The
-- function fences admission first, then signals only registry PIDs whose
-- backend_start still matches pg_stat_activity. It never accepts caller PIDs.
CREATE OR REPLACE FUNCTION powerops_security.revoke_human_database_session(
    p_session_id uuid
)
RETURNS TABLE (
    terminated_backend_count integer,
    remaining_backend_count integer,
    complete boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
SET lock_timeout = '5s'
SET statement_timeout = '20s'
AS $function$
DECLARE
    v_binding powerops_security.human_database_session_binding%ROWTYPE;
    v_backend record;
    v_terminated integer := 0;
    v_remaining integer := 0;
BEGIN
    IF p_session_id IS NULL THEN
        RAISE EXCEPTION 'exact human database session identifier is required'
            USING ERRCODE = '22023';
    END IF;

    SELECT binding.* INTO STRICT v_binding
      FROM powerops_security.human_database_session_binding AS binding
     WHERE binding.session_id = p_session_id
     FOR UPDATE;

    IF v_binding.active THEN
        UPDATE powerops_security.human_database_session_binding
           SET active = false,
               revoked_at = pg_catalog.clock_timestamp(),
               revoked_by = session_user
         WHERE session_id = p_session_id AND active;
    END IF;

    -- A stale PID is never signalled: backend_start must match as well.
    FOR v_backend IN
        SELECT registry.backend_pid, registry.backend_start
          FROM powerops_security.human_database_session_backend AS registry
          JOIN pg_catalog.pg_stat_activity AS activity
            ON activity.pid = registry.backend_pid
           AND activity.backend_start = registry.backend_start
         WHERE registry.session_id = p_session_id
           AND registry.terminated_at IS NULL
    LOOP
        IF pg_catalog.pg_terminate_backend(v_backend.backend_pid) THEN
            v_terminated := v_terminated + 1;
        END IF;
    END LOOP;

    SELECT count(*)::integer INTO v_remaining
      FROM powerops_security.human_database_session_backend AS registry
      JOIN pg_catalog.pg_stat_activity AS activity
        ON activity.pid = registry.backend_pid
       AND activity.backend_start = registry.backend_start
     WHERE registry.session_id = p_session_id
       AND registry.terminated_at IS NULL;

    UPDATE powerops_security.human_database_session_backend AS registry
       SET terminated_at = pg_catalog.clock_timestamp()
     WHERE registry.session_id = p_session_id
       AND registry.terminated_at IS NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_catalog.pg_stat_activity AS activity
            WHERE activity.pid = registry.backend_pid
              AND activity.backend_start = registry.backend_start
       );

    RETURN QUERY SELECT v_terminated, v_remaining, (v_remaining = 0);
EXCEPTION
    WHEN NO_DATA_FOUND OR TOO_MANY_ROWS THEN
        RAISE EXCEPTION 'human database session binding does not exist'
            USING ERRCODE = 'P0002';
END
$function$;

ALTER FUNCTION powerops_security.revoke_human_database_session(uuid)
    OWNER TO powerops_session_control;
REVOKE ALL ON FUNCTION powerops_security.revoke_human_database_session(uuid)
    FROM PUBLIC;
-- Do not grant revocation to provisioner, human logins, or application roles.
-- A separate, customer-approved control-plane grant is intentionally required.

REVOKE CREATE ON SCHEMA powerops_security FROM powerops_session_control;

COMMIT;
