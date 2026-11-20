-- Gate 0.5.14.8.6 PS-02.1A.7: append-only application revocation audit.
-- Requires 0015_human_session_backend_registry.sql.
BEGIN;

DO $roles$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
         WHERE rolname = 'powerops_revocation_auditor'
    ) THEN
        CREATE ROLE powerops_revocation_auditor
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
            NOREPLICATION NOBYPASSRLS;
    END IF;
END
$roles$;

DO $verify_role$
DECLARE
    v_role pg_catalog.pg_roles%ROWTYPE;
BEGIN
    SELECT role.* INTO STRICT v_role
      FROM pg_catalog.pg_roles AS role
     WHERE role.rolname = 'powerops_revocation_auditor';
    IF v_role.rolcanlogin OR v_role.rolsuper OR v_role.rolcreatedb
       OR v_role.rolcreaterole OR v_role.rolinherit
       OR v_role.rolreplication OR v_role.rolbypassrls
       OR EXISTS (
           SELECT 1 FROM pg_catalog.pg_auth_members AS membership
            WHERE membership.member = v_role.oid
               OR membership.roleid = v_role.oid
       ) THEN
        RAISE EXCEPTION
            'powerops_revocation_auditor must be a NOLOGIN, unprivileged, unmembered owner';
    END IF;
END
$verify_role$;

GRANT USAGE ON SCHEMA powerops_security TO powerops_revocation_auditor;
-- The audit SECURITY DEFINER owner may call only the narrow, exact-session
-- verifier; it receives no direct registry or pg_stat_activity access.
GRANT EXECUTE ON FUNCTION
    powerops_security.count_human_session_backends(uuid)
    TO powerops_revocation_auditor;

CREATE TABLE powerops_security.human_session_revocation_audit (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type text NOT NULL CHECK (
        event_type IN (
            'human_database_session_revoked',
            'human_database_session_revocation_attempt'
        )
    ),
    actor_subject text NOT NULL CHECK (length(actor_subject) BETWEEN 1 AND 200),
    session_id uuid NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('verified', 'incomplete')),
    terminated_backend_count integer NOT NULL CHECK (terminated_backend_count >= 0),
    credential_revoked boolean NOT NULL,
    credential_receipt_payload jsonb,
    credential_receipt_signature text,
    admission_fenced boolean NOT NULL,
    backend_termination_verified boolean NOT NULL,
    recorded_by name NOT NULL DEFAULT session_user,
    recorded_at timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp()
);

ALTER TABLE powerops_security.human_session_revocation_audit
    OWNER TO powerops_revocation_auditor;
REVOKE ALL ON powerops_security.human_session_revocation_audit FROM PUBLIC;

-- Remove the previous boolean-only function contract on an in-place upgrade.
-- DROP FUNCTION removes any prior grants as well as the obsolete overload.
DROP FUNCTION IF EXISTS powerops_security.record_human_session_revocation_audit(
    text, text, uuid, text, integer, boolean, boolean, boolean
);

CREATE OR REPLACE FUNCTION powerops_security.record_human_session_revocation_audit(
    p_event_type text,
    p_actor_subject text,
    p_session_id uuid,
    p_outcome text,
    p_terminated_backend_count integer,
    p_credential_revoked boolean,
    p_admission_fenced boolean,
    p_backend_termination_verified boolean,
    p_credential_receipt_payload jsonb,
    p_credential_receipt_signature text
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, powerops_security
AS $function$
DECLARE
    v_audit_id bigint;
    v_remaining_backends integer;
BEGIN
    IF p_event_type NOT IN (
        'human_database_session_revoked',
        'human_database_session_revocation_attempt'
    ) OR p_actor_subject IS NULL
      OR length(p_actor_subject) NOT BETWEEN 1 AND 200
      OR p_session_id IS NULL
      OR p_outcome NOT IN ('verified', 'incomplete')
      OR p_terminated_backend_count IS NULL
      OR p_terminated_backend_count < 0
      OR p_credential_revoked IS NULL
      OR p_admission_fenced IS NULL
      OR p_backend_termination_verified IS NULL
      OR ((p_credential_receipt_payload IS NULL)
          <> (p_credential_receipt_signature IS NULL))
      OR (p_outcome = 'verified'
          AND p_credential_receipt_payload IS NOT NULL
          AND p_credential_receipt_payload ->> 'session_id'
              IS DISTINCT FROM p_session_id::text) THEN
        RAISE EXCEPTION 'invalid session revocation audit event'
            USING ERRCODE = '22023';
    END IF;

    IF p_outcome = 'verified' THEN
        -- The audit writer's assertion is not sufficient: independently prove
        -- that this exact database session exists, is fenced, and has no live
        -- registered backend. The SECURITY DEFINER verifier is owned by the
        -- separately constrained session-control function owner.
        v_remaining_backends :=
            powerops_security.count_human_session_backends(p_session_id);
        IF v_remaining_backends <> 0
           OR NOT p_admission_fenced
           OR NOT p_backend_termination_verified
           OR NOT p_credential_revoked
           OR p_credential_receipt_payload IS NULL
           OR p_credential_receipt_signature IS NULL THEN
            RAISE EXCEPTION
                'verified audit event lacks independently confirmed containment'
                USING ERRCODE = '22023';
        END IF;
    END IF;

    INSERT INTO powerops_security.human_session_revocation_audit (
        event_type, actor_subject, session_id, outcome,
        terminated_backend_count, credential_revoked,
        credential_receipt_payload, credential_receipt_signature,
        admission_fenced, backend_termination_verified
    ) VALUES (
        p_event_type, p_actor_subject, p_session_id, p_outcome,
        p_terminated_backend_count, p_credential_revoked,
        p_credential_receipt_payload, p_credential_receipt_signature,
        p_admission_fenced, p_backend_termination_verified
    )
    RETURNING audit_id INTO v_audit_id;

    RETURN v_audit_id;
END
$function$;

ALTER FUNCTION powerops_security.record_human_session_revocation_audit(
    text, text, uuid, text, integer, boolean, boolean, boolean, jsonb, text
) OWNER TO powerops_revocation_auditor;
REVOKE ALL ON FUNCTION powerops_security.record_human_session_revocation_audit(
    text, text, uuid, text, integer, boolean, boolean, boolean, jsonb, text
) FROM PUBLIC;

-- Customer DBA must grant EXECUTE only to a separately authenticated,
-- dedicated audit-writer login. Do not grant table INSERT/UPDATE/DELETE.
COMMIT;
