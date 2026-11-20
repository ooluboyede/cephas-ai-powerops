-- Gate 0.5.14.8.6 PS-02.1A.5: backend registry for dedicated per-session login roles.
-- Requires 0014_per_session_human_login_identity.sql.
-- This replaces the incompatible 0013 registry model; do NOT apply 0013.
BEGIN;

DO $roles$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'powerops_provisioner'
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'powerops_scope_resolver'
    ) THEN
        RAISE EXCEPTION 'required PowerOps provisioner/scope-resolver roles are missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'powerops_session_control'
    ) THEN
        CREATE ROLE powerops_session_control
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT
            NOREPLICATION NOBYPASSRLS;
    END IF;
END
$roles$;

DO $verify_control_role$
DECLARE
    v_role pg_catalog.pg_roles%ROWTYPE;
BEGIN
    SELECT role.* INTO STRICT v_role
      FROM pg_catalog.pg_roles AS role
     WHERE role.rolname = 'powerops_session_control';
    IF v_role.rolcanlogin OR v_role.rolsuper OR v_role.rolcreatedb
       OR v_role.rolcreaterole OR NOT v_role.rolinherit
       OR v_role.rolreplication OR v_role.rolbypassrls THEN
        RAISE EXCEPTION 'powerops_session_control must be a NOLOGIN, non-privileged INHERIT role';
    END IF;
END
$verify_control_role$;

-- Required to inspect all backend_start values and signal only exact matching
-- registered backends. This NOLOGIN role is a function owner, not a login.
GRANT pg_signal_backend TO powerops_session_control;
GRANT pg_read_all_stats TO powerops_session_control;
GRANT SELECT ON powerops_security.cluster_identity,
                powerops_security.human_session_actor_binding,
                powerops_security.human_actor_binding,
                powerops_security.role_scope_binding
    TO powerops_session_control;
GRANT UPDATE ON powerops_security.human_session_actor_binding,
                powerops_security.role_scope_binding
    TO powerops_session_control;

CREATE TABLE powerops_security.human_session_backend_registry (
    session_id uuid NOT NULL
        REFERENCES powerops_security.human_session_actor_binding(session_id),
    backend_pid integer NOT NULL CHECK (backend_pid > 0),
    backend_start timestamptz NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    terminated_at timestamptz,
    PRIMARY KEY (session_id, backend_pid, backend_start)
);

CREATE INDEX human_session_backend_registry_live_idx
    ON powerops_security.human_session_backend_registry(session_id)
    WHERE terminated_at IS NULL;

CREATE TABLE powerops_security.human_session_backend_audit (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id uuid NOT NULL,
    event_type text NOT NULL CHECK (
        event_type IN ('backend_registered', 'session_fenced',
                       'backend_termination_requested', 'termination_incomplete',
                       'backend_termination_verified')
    ),
    backend_pid integer,
    backend_start timestamptz,
    actor_name name NOT NULL DEFAULT session_user,
    occurred_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    detail text NOT NULL CHECK (length(detail) BETWEEN 1 AND 300)
);

ALTER TABLE powerops_security.human_session_backend_registry
    OWNER TO powerops_session_control;
ALTER TABLE powerops_security.human_session_backend_audit
    OWNER TO powerops_session_control;
REVOKE ALL ON powerops_security.human_session_backend_registry FROM PUBLIC;
REVOKE ALL ON powerops_security.human_session_backend_audit FROM PUBLIC;
REVOKE ALL ON powerops_security.human_session_backend_registry
    FROM powerops_provisioner, powerops_scope_resolver;
REVOKE ALL ON powerops_security.human_session_backend_audit
    FROM powerops_provisioner, powerops_scope_resolver;

-- Runs on the actual dedicated per-session login. No caller-provided PID,
-- backend_start, role OID, tenant, BU, or actor identity is accepted.
CREATE OR REPLACE FUNCTION powerops_security.register_human_session_backend(
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
    v_binding powerops_security.human_session_actor_binding%ROWTYPE;
    v_backend_start timestamptz;
BEGIN
    IF p_session_id IS NULL THEN
        RAISE EXCEPTION 'exact human session identifier is required'
            USING ERRCODE = '22023';
    END IF;

    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci
     WHERE ci.singleton;

    SELECT role.oid INTO STRICT v_role_oid
      FROM pg_catalog.pg_roles AS role
     WHERE role.rolname = session_user;

    -- Shared row lock is the admission lock. 0014 retirement updates this
    -- same row, so registration and revocation cannot pass each other.
    SELECT binding.* INTO STRICT v_binding
      FROM powerops_security.human_session_actor_binding AS binding
     WHERE binding.session_id = p_session_id
       AND binding.cluster_id = v_cluster_id
       AND binding.session_role_oid = v_role_oid
       AND binding.session_role_name = session_user
       AND binding.active
       AND binding.expires_at > pg_catalog.clock_timestamp()
     FOR SHARE;

    PERFORM 1
      FROM powerops_security.human_actor_binding AS actor
      JOIN powerops_security.role_scope_binding AS actor_scope
        ON actor_scope.cluster_id = actor.cluster_id
       AND actor_scope.role_oid = actor.role_oid
     WHERE actor.cluster_id = v_binding.cluster_id
       AND actor.role_oid = v_binding.actor_role_oid
       AND actor.issuer = v_binding.issuer
       AND actor.subject = v_binding.subject
       AND actor.tenant_id = v_binding.tenant_id
       AND actor.business_unit_id = v_binding.business_unit_id
       AND actor.active
       AND actor_scope.active
       AND (actor.expires_at IS NULL
            OR actor.expires_at > pg_catalog.clock_timestamp());
    IF NOT FOUND THEN
        RAISE EXCEPTION 'human actor entitlement is no longer active'
            USING ERRCODE = '42501';
    END IF;

    SELECT activity.backend_start INTO STRICT v_backend_start
      FROM pg_catalog.pg_stat_activity AS activity
     WHERE activity.pid = pg_catalog.pg_backend_pid();

    INSERT INTO powerops_security.human_session_backend_registry (
        session_id, backend_pid, backend_start
    ) VALUES (
        p_session_id, pg_catalog.pg_backend_pid(), v_backend_start
    )
    ON CONFLICT (session_id, backend_pid, backend_start) DO NOTHING;

    INSERT INTO powerops_security.human_session_backend_audit (
        session_id, event_type, backend_pid, backend_start, detail
    ) VALUES (
        p_session_id, 'backend_registered', pg_catalog.pg_backend_pid(),
        v_backend_start, 'Database-derived backend registration'
    );

    RETURN true;
EXCEPTION
    WHEN NO_DATA_FOUND OR TOO_MANY_ROWS THEN
        RAISE EXCEPTION 'human session is unknown, expired, revoked, or bound to another login'
            USING ERRCODE = '42501';
END
$function$;

ALTER FUNCTION powerops_security.register_human_session_backend(uuid)
    OWNER TO powerops_session_control;
REVOKE ALL ON FUNCTION powerops_security.register_human_session_backend(uuid)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.register_human_session_backend(uuid)
    TO powerops_provisioner;

-- Grant the registration capability to each newly provisioned session login.
-- The provisioner is the only role allowed to perform this controlled grant.
CREATE OR REPLACE FUNCTION powerops_security.grant_human_session_backend_registration(
    p_session_role_name name
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_binding powerops_security.human_session_actor_binding%ROWTYPE;
BEGIN
    SELECT binding.* INTO STRICT v_binding
      FROM powerops_security.human_session_actor_binding AS binding
     WHERE binding.session_role_name = p_session_role_name
       AND binding.active
       AND binding.expires_at > pg_catalog.clock_timestamp();

    EXECUTE pg_catalog.format(
        'GRANT EXECUTE ON FUNCTION powerops_security.register_human_session_backend(uuid) TO %I',
        p_session_role_name
    );
END
$function$;

ALTER FUNCTION powerops_security.grant_human_session_backend_registration(name)
    OWNER TO powerops_provisioner;
REVOKE ALL ON FUNCTION powerops_security.grant_human_session_backend_registration(name)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.grant_human_session_backend_registration(name)
    TO powerops_provisioner;

-- Control-plane termination is deliberately separate from session retirement.
-- The caller must first commit retire_human_session_login(session_id, reason),
-- which fences admission on the same session binding row and sets NOLOGIN.
-- This function never accepts a caller-supplied PID or backend_start.
CREATE OR REPLACE FUNCTION powerops_security.terminate_human_session_backends(
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
    v_binding powerops_security.human_session_actor_binding%ROWTYPE;
    v_backend record;
    v_terminated integer := 0;
    v_remaining integer := 0;
BEGIN
    IF p_session_id IS NULL THEN
        RAISE EXCEPTION 'exact human session identifier is required'
            USING ERRCODE = '22023';
    END IF;

    SELECT binding.* INTO STRICT v_binding
      FROM powerops_security.human_session_actor_binding AS binding
     WHERE binding.session_id = p_session_id
     FOR UPDATE;

    IF v_binding.active OR v_binding.expires_at > pg_catalog.clock_timestamp()
       AND EXISTS (
           SELECT 1 FROM powerops_security.human_session_actor_binding AS active_binding
            WHERE active_binding.session_id = p_session_id AND active_binding.active
       ) THEN
        RAISE EXCEPTION 'session must be fenced before backend termination'
            USING ERRCODE = '55000';
    END IF;

    INSERT INTO powerops_security.human_session_backend_audit (
        session_id, event_type, detail
    ) VALUES (
        p_session_id, 'session_fenced',
        'Termination requested after session admission fence'
    );

    FOR v_backend IN
        SELECT registry.backend_pid, registry.backend_start
          FROM powerops_security.human_session_backend_registry AS registry
          JOIN pg_catalog.pg_stat_activity AS activity
            ON activity.pid = registry.backend_pid
           AND activity.backend_start = registry.backend_start
         WHERE registry.session_id = p_session_id
           AND registry.terminated_at IS NULL
    LOOP
        INSERT INTO powerops_security.human_session_backend_audit (
            session_id, event_type, backend_pid, backend_start, detail
        ) VALUES (
            p_session_id, 'backend_termination_requested',
            v_backend.backend_pid, v_backend.backend_start,
            'Exact PID and backend_start match verified before signal'
        );

        IF pg_catalog.pg_terminate_backend(v_backend.backend_pid) THEN
            v_terminated := v_terminated + 1;
        END IF;
    END LOOP;

    SELECT count(*)::integer INTO v_remaining
      FROM powerops_security.human_session_backend_registry AS registry
      JOIN pg_catalog.pg_stat_activity AS activity
        ON activity.pid = registry.backend_pid
       AND activity.backend_start = registry.backend_start
     WHERE registry.session_id = p_session_id
       AND registry.terminated_at IS NULL;

    UPDATE powerops_security.human_session_backend_registry AS registry
       SET terminated_at = pg_catalog.clock_timestamp()
     WHERE registry.session_id = p_session_id
       AND registry.terminated_at IS NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_catalog.pg_stat_activity AS activity
            WHERE activity.pid = registry.backend_pid
              AND activity.backend_start = registry.backend_start
       );

    IF v_remaining = 0 THEN
        INSERT INTO powerops_security.human_session_backend_audit (
            session_id, event_type, detail
        ) VALUES (
            p_session_id, 'backend_termination_verified',
            'No registered matching backend remains'
        );
    ELSE
        INSERT INTO powerops_security.human_session_backend_audit (
            session_id, event_type, detail
        ) VALUES (
            p_session_id, 'termination_incomplete',
            'One or more registered matching backends remain; retry required'
        );
    END IF;

    RETURN QUERY SELECT v_terminated, v_remaining, (v_remaining = 0);
EXCEPTION
    WHEN NO_DATA_FOUND OR TOO_MANY_ROWS THEN
        RAISE EXCEPTION 'human session binding does not exist'
            USING ERRCODE = 'P0002';
END
$function$;

ALTER FUNCTION powerops_security.terminate_human_session_backends(uuid)
    OWNER TO powerops_session_control;
REVOKE ALL ON FUNCTION powerops_security.terminate_human_session_backends(uuid)
    FROM PUBLIC;
-- No grant to provisioner, session roles, or application roles. A customer DBA
-- must grant EXECUTE to a separately authenticated revocation control plane.

REVOKE CREATE ON SCHEMA powerops_security FROM powerops_session_control;
COMMIT;
