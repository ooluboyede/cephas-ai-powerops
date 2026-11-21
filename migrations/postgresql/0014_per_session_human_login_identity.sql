-- Gate 0.5.14.8.6 PS-02.1A.3: dedicated per-session PostgreSQL login identities.
-- Additive replacement for the unsafe actor-role-as-session-role assumption.
-- Apply after migrations 0010-0012. Migration 0013 is intentionally not required.
BEGIN;

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'powerops_provisioner')
       OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'powerops_scope_resolver') THEN
        RAISE EXCEPTION 'required PowerOps provisioner/scope-resolver roles are missing';
    END IF;
END
$roles$;

CREATE TABLE powerops_security.human_session_actor_binding (
    session_id uuid PRIMARY KEY,
    cluster_id uuid NOT NULL,
    session_role_oid oid NOT NULL,
    session_role_name name NOT NULL,
    actor_role_oid oid NOT NULL,
    issuer text NOT NULL,
    subject text NOT NULL,
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    expires_at timestamptz NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    created_by name NOT NULL DEFAULT session_user,
    revoked_at timestamptz,
    revoked_by name,
    revocation_reason text,
    UNIQUE (cluster_id, session_role_oid),
    UNIQUE (cluster_id, session_role_name),
    FOREIGN KEY (cluster_id, session_role_oid)
        REFERENCES powerops_security.role_scope_binding(cluster_id, role_oid),
    FOREIGN KEY (cluster_id, actor_role_oid)
        REFERENCES powerops_security.human_actor_binding(cluster_id, role_oid),
    CHECK (expires_at > created_at),
    CHECK (
      (active AND revoked_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL)
      OR
      (NOT active AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL
       AND revocation_reason IS NOT NULL)
    )
);
ALTER TABLE powerops_security.human_session_actor_binding OWNER TO powerops_provisioner;
REVOKE ALL ON powerops_security.human_session_actor_binding FROM PUBLIC;
REVOKE ALL ON powerops_security.human_session_actor_binding
    FROM powerops_provisioner, powerops_scope_resolver;
GRANT SELECT, INSERT, UPDATE ON powerops_security.human_session_actor_binding
    TO powerops_provisioner;
GRANT SELECT ON powerops_security.human_session_actor_binding
    TO powerops_scope_resolver;

CREATE INDEX human_session_actor_binding_active_actor_idx
    ON powerops_security.human_session_actor_binding(cluster_id, actor_role_oid)
    WHERE active;

-- The broker supplies the verified actor key and a fresh random role name.
-- The database resolves the actor and entitlements from its protected record;
-- it never accepts caller-supplied OIDs, role attributes or finance privileges.
CREATE OR REPLACE FUNCTION powerops_security.provision_human_session_login(
    p_session_id uuid,
    p_session_role_name name,
    p_issuer text,
    p_subject text,
    p_tenant_id uuid,
    p_business_unit_id uuid,
    p_expires_at timestamptz
)
RETURNS oid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_cluster_id uuid;
    v_actor powerops_security.human_actor_binding%ROWTYPE;
    v_session_role_oid oid;
BEGIN
    IF p_session_id IS NULL OR p_session_role_name IS NULL
       OR p_session_role_name::text !~ '^pwr_[a-z0-9_]{1,40}$'
       OR p_issuer IS NULL OR p_subject IS NULL
       OR p_tenant_id IS NULL OR p_business_unit_id IS NULL
       OR p_expires_at IS NULL
       OR p_expires_at <= pg_catalog.clock_timestamp()
       OR p_expires_at > pg_catalog.clock_timestamp() + interval '5 minutes' THEN
        RAISE EXCEPTION 'invalid human session provisioning request'
            USING ERRCODE = '22023';
    END IF;

    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci
     WHERE ci.singleton
     FOR UPDATE;

    SELECT actor.* INTO STRICT v_actor
      FROM powerops_security.human_actor_binding AS actor
      JOIN powerops_security.role_scope_binding AS actor_scope
        ON actor_scope.cluster_id = actor.cluster_id
       AND actor_scope.role_oid = actor.role_oid
     WHERE actor.cluster_id = v_cluster_id
       AND actor.issuer = p_issuer
       AND actor.subject = p_subject
       AND actor.tenant_id = p_tenant_id
       AND actor.business_unit_id = p_business_unit_id
       AND actor.active
       AND actor_scope.active
       AND (actor.expires_at IS NULL OR actor.expires_at > pg_catalog.clock_timestamp())
     FOR SHARE OF actor;

    IF p_expires_at > COALESCE(v_actor.expires_at, p_expires_at) THEN
        RAISE EXCEPTION 'session lease exceeds actor entitlement expiry'
            USING ERRCODE = '22023';
    END IF;

    -- Reuse the established NOLOGIN-first lifecycle. It enforces the role
    -- name/OID tombstones, least-privilege attributes, scope binding and
    -- LOGIN as the final transaction step.
    v_session_role_oid := powerops_security.provision_scope_login(
        p_session_role_name, p_tenant_id, 'business_unit', p_business_unit_id
    );

    INSERT INTO powerops_security.human_session_actor_binding (
        session_id, cluster_id, session_role_oid, session_role_name,
        actor_role_oid, issuer, subject, tenant_id, business_unit_id, expires_at
    ) VALUES (
        p_session_id, v_cluster_id, v_session_role_oid, p_session_role_name,
        v_actor.role_oid, v_actor.issuer, v_actor.subject, v_actor.tenant_id,
        v_actor.business_unit_id, p_expires_at
    );

    EXECUTE pg_catalog.format(
        'GRANT EXECUTE ON FUNCTION powerops_security.resolve_authenticated_human_actor_v2() TO %I',
        p_session_role_name
    );
    PERFORM powerops_security.grant_revenue_assurance_access(p_session_role_name);

    RETURN v_session_role_oid;
EXCEPTION
    WHEN unique_violation THEN
        RAISE EXCEPTION 'human session identifier or database role has already been used'
            USING ERRCODE = '23505';
END
$function$;

ALTER FUNCTION powerops_security.provision_human_session_login(
    uuid, name, text, text, uuid, uuid, timestamptz
) OWNER TO powerops_provisioner;
REVOKE ALL ON FUNCTION powerops_security.provision_human_session_login(
    uuid, name, text, text, uuid, uuid, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.provision_human_session_login(
    uuid, name, text, text, uuid, uuid, timestamptz
) TO powerops_provisioner;

-- Session expiry/revocation and actor-wide revocation must also fence the
-- lower-level scope resolver used by RLS, not merely finance-specific APIs.
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
    v_session powerops_security.human_session_actor_binding%ROWTYPE;
    v_actor powerops_security.human_actor_binding%ROWTYPE;
    v_retired boolean;
BEGIN
    v_role_name := session_user;
    SELECT role.oid INTO STRICT v_role_oid
      FROM pg_catalog.pg_roles AS role
     WHERE role.rolname = session_user AND role.rolcanlogin;

    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci
     WHERE ci.singleton;

    SELECT session_binding.* INTO v_session
      FROM powerops_security.human_session_actor_binding AS session_binding
     WHERE session_binding.cluster_id = v_cluster_id
       AND session_binding.session_role_oid = v_role_oid;

    IF FOUND THEN
        IF NOT v_session.active
           OR v_session.expires_at <= pg_catalog.clock_timestamp() THEN
            RAISE EXCEPTION 'human database session is revoked or expired'
                USING ERRCODE = '42501';
        END IF;

        SELECT actor.* INTO STRICT v_actor
          FROM powerops_security.human_actor_binding AS actor
         WHERE actor.cluster_id = v_session.cluster_id
           AND actor.role_oid = v_session.actor_role_oid
           AND actor.issuer = v_session.issuer
           AND actor.subject = v_session.subject
           AND actor.tenant_id = v_session.tenant_id
           AND actor.business_unit_id = v_session.business_unit_id
           AND actor.active
           AND (actor.expires_at IS NULL
                OR actor.expires_at > pg_catalog.clock_timestamp());
    END IF;

    SELECT EXISTS (
        SELECT 1 FROM powerops_security.retired_role_identity AS retired
         WHERE retired.cluster_id = v_cluster_id
           AND (retired.role_oid = v_role_oid OR retired.role_name = v_role_name)
    ) INTO v_retired;
    IF v_retired THEN
        RAISE EXCEPTION 'authenticated database identity is retired'
            USING ERRCODE = '42501';
    END IF;

    SELECT binding.* INTO STRICT v_binding
      FROM powerops_security.role_scope_binding AS binding
     WHERE binding.cluster_id = v_cluster_id
       AND binding.role_oid = v_role_oid
       AND binding.role_name = v_role_name
       AND binding.active;

    IF FOUND AND v_session.session_id IS NOT NULL
       AND (v_binding.tenant_id <> v_session.tenant_id
            OR v_binding.business_unit_id <> v_session.business_unit_id
            OR v_binding.scope_kind <> 'business_unit') THEN
        RAISE EXCEPTION 'session login scope does not match its protected actor binding'
            USING ERRCODE = '42501';
    END IF;

    RETURN QUERY SELECT v_cluster_id, v_binding.tenant_id,
        v_binding.scope_kind, v_binding.business_unit_id, v_role_oid;
EXCEPTION
    WHEN NO_DATA_FOUND OR TOO_MANY_ROWS THEN
        RAISE EXCEPTION 'authenticated database identity has no unique active scope'
            USING ERRCODE = '42501';
END
$function$;

ALTER FUNCTION powerops_security.resolve_authenticated_scope()
    OWNER TO powerops_scope_resolver;
REVOKE ALL ON FUNCTION powerops_security.resolve_authenticated_scope() FROM PUBLIC;

-- Resolve session login -> immutable actor binding -> current actor entitlements.
-- Preserve legacy directly provisioned human logins for backward compatibility;
-- a role with a session binding never falls back if that binding is inactive.
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
    v_session powerops_security.human_session_actor_binding%ROWTYPE;
    v_actor powerops_security.human_actor_binding%ROWTYPE;
    v_actor_role_oid oid;
BEGIN
    SELECT * INTO STRICT v_scope
      FROM powerops_security.resolve_authenticated_scope();

    SELECT binding.* INTO v_session
      FROM powerops_security.human_session_actor_binding AS binding
     WHERE binding.cluster_id = v_scope.cluster_id
       AND binding.session_role_oid = v_scope.authenticated_role_oid;

    IF FOUND THEN
        IF NOT v_session.active
           OR v_session.expires_at <= pg_catalog.clock_timestamp()
           OR v_session.tenant_id <> v_scope.tenant_id
           OR v_session.business_unit_id <> v_scope.business_unit_id THEN
            RAISE EXCEPTION 'human database session is revoked, expired or scope-mismatched'
                USING ERRCODE = '42501';
        END IF;
        v_actor_role_oid := v_session.actor_role_oid;
    ELSE
        -- Legacy actor login path. A session role with a row above can never
        -- downgrade to this path after revocation.
        v_actor_role_oid := v_scope.authenticated_role_oid;
    END IF;

    SELECT actor.* INTO STRICT v_actor
      FROM powerops_security.human_actor_binding AS actor
     WHERE actor.cluster_id = v_scope.cluster_id
       AND actor.role_oid = v_actor_role_oid
       AND actor.tenant_id = v_scope.tenant_id
       AND actor.business_unit_id = v_scope.business_unit_id
       AND actor.active
       AND (actor.expires_at IS NULL
            OR actor.expires_at > pg_catalog.clock_timestamp());

    IF FOUND AND v_session.session_id IS NOT NULL
       AND (v_actor.issuer <> v_session.issuer OR v_actor.subject <> v_session.subject) THEN
        RAISE EXCEPTION 'session actor binding no longer matches its authoritative actor'
            USING ERRCODE = '42501';
    END IF;

    RETURN QUERY SELECT
        v_actor.cluster_id, v_actor.tenant_id, v_actor.business_unit_id,
        v_actor.role_oid, v_actor.issuer || '|' || v_actor.subject,
        v_actor.finance_operator, v_actor.finance_verifier;
EXCEPTION
    WHEN NO_DATA_FOUND OR TOO_MANY_ROWS THEN
        RAISE EXCEPTION 'authenticated database identity has no unique active human actor mapping'
            USING ERRCODE = '42501';
END
$function$;

ALTER FUNCTION powerops_security.resolve_authenticated_human_actor_v2()
    OWNER TO powerops_scope_resolver;
REVOKE ALL ON FUNCTION powerops_security.resolve_authenticated_human_actor_v2() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.resolve_authenticated_human_actor_v2()
    TO powerops_provisioner WITH GRANT OPTION;

-- Exact-session retirement fences future logins and all human resolver calls.
-- Existing physical backends are NOT terminated by this function; that is
-- deliberately reserved for the separately reviewed PS-02 backend registry.
CREATE OR REPLACE FUNCTION powerops_security.retire_human_session_login(
    p_session_id uuid,
    p_retirement_reason text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_session powerops_security.human_session_actor_binding%ROWTYPE;
BEGIN
    IF p_session_id IS NULL OR p_retirement_reason IS NULL
       OR length(btrim(p_retirement_reason)) < 8
       OR length(p_retirement_reason) > 500 THEN
        RAISE EXCEPTION 'invalid human session retirement request'
            USING ERRCODE = '22023';
    END IF;

    SELECT binding.* INTO v_session
      FROM powerops_security.human_session_actor_binding AS binding
     WHERE binding.session_id = p_session_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'human session does not exist'
            USING ERRCODE = 'P0002';
    END IF;
    IF NOT v_session.active THEN
        RETURN;
    END IF;

    UPDATE powerops_security.human_session_actor_binding
       SET active = false, revoked_at = pg_catalog.clock_timestamp(),
           revoked_by = session_user, revocation_reason = p_retirement_reason
     WHERE session_id = p_session_id AND active;

    UPDATE powerops_security.role_scope_binding
       SET active = false
     WHERE cluster_id = v_session.cluster_id
       AND role_oid = v_session.session_role_oid
       AND role_name = v_session.session_role_name;

    INSERT INTO powerops_security.retired_role_identity (
        cluster_id, role_oid, role_name, retirement_reason
    ) VALUES (
        v_session.cluster_id, v_session.session_role_oid,
        v_session.session_role_name, p_retirement_reason
    ) ON CONFLICT DO NOTHING;

    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
         WHERE oid = v_session.session_role_oid
           AND rolname = v_session.session_role_name
    ) THEN
        EXECUTE pg_catalog.format('ALTER ROLE %I NOLOGIN', v_session.session_role_name);
    END IF;
END
$function$;

ALTER FUNCTION powerops_security.retire_human_session_login(uuid, text)
    OWNER TO powerops_provisioner;
REVOKE ALL ON FUNCTION powerops_security.retire_human_session_login(uuid, text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.retire_human_session_login(uuid, text)
    TO powerops_provisioner;

-- Actor-wide revocation also retires every session login derived from the
-- actor. This preserves the existing function contract while closing the
-- session-role bypass introduced by one-login-per-session provisioning.
CREATE OR REPLACE FUNCTION powerops_security.revoke_human_actor_login(
    p_role_name name,
    p_revocation_reason text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_cluster_id uuid;
    v_role_oid oid;
    v_session record;
BEGIN
    IF p_role_name IS NULL OR p_revocation_reason IS NULL
       OR length(btrim(p_revocation_reason)) < 8
       OR length(p_revocation_reason) > 500 THEN
        RAISE EXCEPTION 'invalid human actor revocation request'
            USING ERRCODE = '22023';
    END IF;

    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci
     WHERE ci.singleton;

    SELECT actor.role_oid INTO STRICT v_role_oid
      FROM powerops_security.human_actor_binding AS actor
      JOIN powerops_security.role_scope_binding AS actor_scope
        ON actor_scope.cluster_id = actor.cluster_id
       AND actor_scope.role_oid = actor.role_oid
       AND actor_scope.role_name = p_role_name
     WHERE actor.cluster_id = v_cluster_id
       AND actor.active
     FOR UPDATE OF actor;

    UPDATE powerops_security.human_actor_binding
       SET active = false, revoked_at = pg_catalog.clock_timestamp(),
           revoked_by = session_user, revocation_reason = p_revocation_reason
     WHERE cluster_id = v_cluster_id AND role_oid = v_role_oid;

    INSERT INTO powerops_security.retired_role_identity (
        cluster_id, role_oid, role_name, retirement_reason
    ) VALUES (
        v_cluster_id, v_role_oid, p_role_name, p_revocation_reason
    ) ON CONFLICT DO NOTHING;

    UPDATE powerops_security.role_scope_binding
       SET active = false
     WHERE cluster_id = v_cluster_id AND role_oid = v_role_oid;

    EXECUTE pg_catalog.format('ALTER ROLE %I NOLOGIN', p_role_name);

    FOR v_session IN
        SELECT binding.session_id, binding.session_role_oid, binding.session_role_name
          FROM powerops_security.human_session_actor_binding AS binding
         WHERE binding.cluster_id = v_cluster_id
           AND binding.actor_role_oid = v_role_oid
           AND binding.active
         FOR UPDATE
    LOOP
        UPDATE powerops_security.human_session_actor_binding
           SET active = false, revoked_at = pg_catalog.clock_timestamp(),
               revoked_by = session_user, revocation_reason = p_revocation_reason
         WHERE session_id = v_session.session_id AND active;

        UPDATE powerops_security.role_scope_binding
           SET active = false
         WHERE cluster_id = v_cluster_id
           AND role_oid = v_session.session_role_oid;

        INSERT INTO powerops_security.retired_role_identity (
            cluster_id, role_oid, role_name, retirement_reason
        ) VALUES (
            v_cluster_id, v_session.session_role_oid,
            v_session.session_role_name, p_revocation_reason
        ) ON CONFLICT DO NOTHING;

        IF EXISTS (
            SELECT 1 FROM pg_catalog.pg_roles
             WHERE oid = v_session.session_role_oid
               AND rolname = v_session.session_role_name
        ) THEN
            EXECUTE pg_catalog.format(
                'ALTER ROLE %I NOLOGIN', v_session.session_role_name
            );
        END IF;
    END LOOP;
END
$function$;

ALTER FUNCTION powerops_security.revoke_human_actor_login(name, text)
    OWNER TO powerops_provisioner;
REVOKE ALL ON FUNCTION powerops_security.revoke_human_actor_login(name, text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.revoke_human_actor_login(name, text)
    TO powerops_provisioner;

-- Audit actor detection must include dedicated session roles. An inactive or
-- expired session row is still recognized as human and therefore cannot fall
-- through to legacy service-role audit behavior.
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

    IF EXISTS (
        SELECT 1 FROM powerops_security.human_actor_binding AS actor
         WHERE actor.cluster_id = v_cluster_id
           AND actor.role_oid = v_session_role_oid
    ) OR EXISTS (
        SELECT 1 FROM powerops_security.human_session_actor_binding AS session_binding
         WHERE session_binding.cluster_id = v_cluster_id
           AND session_binding.session_role_oid = v_session_role_oid
    ) THEN
        SELECT actor.actor_subject INTO STRICT v_actor_subject
          FROM powerops_security.resolve_authenticated_human_actor_v2() AS actor;
        NEW.actor_subject := v_actor_subject;
    END IF;

    RETURN NEW;
END
$function$;

GRANT CREATE ON SCHEMA revenue_assurance TO powerops_scope_resolver;
ALTER FUNCTION revenue_assurance.bind_human_audit_actor()
    OWNER TO powerops_scope_resolver;
REVOKE CREATE ON SCHEMA revenue_assurance FROM powerops_scope_resolver;
REVOKE ALL ON FUNCTION revenue_assurance.bind_human_audit_actor() FROM PUBLIC;

COMMIT;
