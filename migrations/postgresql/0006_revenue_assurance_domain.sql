-- PowerOps Revenue Assurance Gate 0.1 — additive domain schema.
-- Apply only after migrations 0001–0005 and successful Gate 1A–1D setup.
-- Extends the existing authenticated session_user -> scope -> RLS design.
BEGIN;

CREATE SCHEMA revenue_assurance;
REVOKE ALL ON SCHEMA revenue_assurance FROM PUBLIC;

CREATE TABLE revenue_assurance.source_batches (
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    batch_id uuid NOT NULL,
    source_system text NOT NULL CHECK (length(btrim(source_system)) BETWEEN 1 AND 120),
    dataset_type text NOT NULL CHECK (length(btrim(dataset_type)) BETWEEN 1 AND 80),
    source_snapshot_hash char(64) NOT NULL
        CHECK (source_snapshot_hash ~ '^[0-9a-f]{64}$'),
    record_count bigint NOT NULL CHECK (record_count >= 0),
    batch_status text NOT NULL CHECK (batch_status IN
        ('received','validated','quarantined','rejected','processed')),
    received_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    PRIMARY KEY (tenant_id, business_unit_id, batch_id),
    FOREIGN KEY (tenant_id, business_unit_id)
        REFERENCES powerops_data.business_units (tenant_id, business_unit_id),
    CHECK (processed_at IS NULL OR processed_at >= received_at)
);

CREATE TABLE revenue_assurance.findings (
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    finding_id uuid NOT NULL,
    batch_id uuid NOT NULL,
    finding_code text NOT NULL CHECK (length(btrim(finding_code)) BETWEEN 1 AND 80),
    category text NOT NULL CHECK (category IN
        ('billing_gap','payment_mismatch','meter_anomaly','energy_balance','tariff_mismatch')),
    finding_status text NOT NULL DEFAULT 'new' CHECK (finding_status IN
        ('new','under_review','approved','rejected','resolved')),
    currency char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    estimated_exposure numeric(20,4) NOT NULL CHECK (estimated_exposure >= 0),
    evidence_completeness smallint NOT NULL CHECK (evidence_completeness BETWEEN 0 AND 100),
    evidence_summary text NOT NULL CHECK (length(btrim(evidence_summary)) BETWEEN 1 AND 2000),
    evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(evidence_refs) = 'array'),
    recommendation text NOT NULL CHECK (length(btrim(recommendation)) BETWEEN 1 AND 2000),
    rule_version text NOT NULL,
    calculation_version text NOT NULL,
    model_version text,
    idempotency_key text NOT NULL CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 160),
    observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, business_unit_id, finding_id),
    UNIQUE (tenant_id, business_unit_id, idempotency_key),
    FOREIGN KEY (tenant_id, business_unit_id, batch_id)
        REFERENCES revenue_assurance.source_batches
            (tenant_id, business_unit_id, batch_id),
    FOREIGN KEY (tenant_id, business_unit_id)
        REFERENCES powerops_data.business_units (tenant_id, business_unit_id)
);

CREATE TABLE revenue_assurance.investigation_cases (
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    case_id uuid NOT NULL,
    finding_id uuid NOT NULL,
    case_status text NOT NULL DEFAULT 'open' CHECK (case_status IN
        ('open','in_review','awaiting_evidence','approved','rejected','closed')),
    summary text NOT NULL CHECK (length(btrim(summary)) BETWEEN 5 AND 200),
    opening_reason text NOT NULL CHECK (length(btrim(opening_reason)) BETWEEN 10 AND 2000),
    assigned_to text,
    created_by text NOT NULL CHECK (length(btrim(created_by)) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz,
    PRIMARY KEY (tenant_id, business_unit_id, case_id),
    FOREIGN KEY (tenant_id, business_unit_id, finding_id)
        REFERENCES revenue_assurance.findings
            (tenant_id, business_unit_id, finding_id),
    FOREIGN KEY (tenant_id, business_unit_id)
        REFERENCES powerops_data.business_units (tenant_id, business_unit_id),
    CHECK (closed_at IS NULL OR closed_at >= created_at)
);

CREATE TABLE revenue_assurance.case_decisions (
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    decision_id uuid NOT NULL,
    case_id uuid NOT NULL,
    decision text NOT NULL CHECK (decision IN
        ('approve','reject','request_more_evidence')),
    actor_subject text NOT NULL CHECK (length(btrim(actor_subject)) BETWEEN 1 AND 200),
    reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 10 AND 2000),
    decided_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, business_unit_id, decision_id),
    FOREIGN KEY (tenant_id, business_unit_id, case_id)
        REFERENCES revenue_assurance.investigation_cases
            (tenant_id, business_unit_id, case_id),
    FOREIGN KEY (tenant_id, business_unit_id)
        REFERENCES powerops_data.business_units (tenant_id, business_unit_id)
);

CREATE TABLE revenue_assurance.recovery_outcomes (
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    outcome_id uuid NOT NULL,
    case_id uuid NOT NULL,
    amount numeric(20,4) NOT NULL CHECK (amount > 0),
    currency char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    outcome text NOT NULL CHECK (outcome IN
        ('reported','verified','reversed','disputed')),
    evidence_reference text NOT NULL
        CHECK (length(btrim(evidence_reference)) BETWEEN 3 AND 240),
    recorded_by text NOT NULL CHECK (length(btrim(recorded_by)) BETWEEN 1 AND 200),
    verified_by text,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    verified_at timestamptz,
    PRIMARY KEY (tenant_id, business_unit_id, outcome_id),
    FOREIGN KEY (tenant_id, business_unit_id, case_id)
        REFERENCES revenue_assurance.investigation_cases
            (tenant_id, business_unit_id, case_id),
    FOREIGN KEY (tenant_id, business_unit_id)
        REFERENCES powerops_data.business_units (tenant_id, business_unit_id),
    CHECK (
        (outcome = 'verified' AND verified_by IS NOT NULL AND verified_at IS NOT NULL)
        OR outcome <> 'verified'
    )
);

CREATE TABLE revenue_assurance.audit_events (
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    event_id uuid NOT NULL,
    request_id text NOT NULL CHECK (length(btrim(request_id)) BETWEEN 1 AND 160),
    actor_subject text NOT NULL CHECK (length(btrim(actor_subject)) BETWEEN 1 AND 200),
    action text NOT NULL CHECK (length(btrim(action)) BETWEEN 1 AND 120),
    entity_type text NOT NULL CHECK (length(btrim(entity_type)) BETWEEN 1 AND 80),
    entity_id text NOT NULL CHECK (length(btrim(entity_id)) BETWEEN 1 AND 160),
    event_data jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(event_data) = 'object'),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, business_unit_id, event_id),
    FOREIGN KEY (tenant_id, business_unit_id)
        REFERENCES powerops_data.business_units (tenant_id, business_unit_id)
);

CREATE INDEX findings_scope_status_created_idx
    ON revenue_assurance.findings
       (tenant_id, business_unit_id, finding_status, created_at DESC);
CREATE INDEX findings_scope_category_idx
    ON revenue_assurance.findings (tenant_id, business_unit_id, category);
CREATE INDEX cases_scope_status_created_idx
    ON revenue_assurance.investigation_cases
       (tenant_id, business_unit_id, case_status, created_at DESC);
CREATE INDEX decisions_scope_case_time_idx
    ON revenue_assurance.case_decisions
       (tenant_id, business_unit_id, case_id, decided_at DESC);
CREATE INDEX recovery_scope_case_time_idx
    ON revenue_assurance.recovery_outcomes
       (tenant_id, business_unit_id, case_id, recorded_at DESC);
CREATE INDEX audit_scope_time_idx
    ON revenue_assurance.audit_events
       (tenant_id, business_unit_id, occurred_at DESC);

DO $rls$
DECLARE
    v_table text;
BEGIN
    FOREACH v_table IN ARRAY ARRAY[
        'source_batches','findings','investigation_cases','case_decisions',
        'recovery_outcomes','audit_events'
    ] LOOP
        EXECUTE pg_catalog.format(
            'ALTER TABLE revenue_assurance.%I ENABLE ROW LEVEL SECURITY', v_table
        );
        EXECUTE pg_catalog.format(
            'ALTER TABLE revenue_assurance.%I FORCE ROW LEVEL SECURITY', v_table
        );
        EXECUTE pg_catalog.format(
            'CREATE POLICY %I ON revenue_assurance.%I FOR ALL USING ' ||
            '(powerops_security.row_scope_permits(tenant_id, business_unit_id)) ' ||
            'WITH CHECK (powerops_security.row_scope_permits(tenant_id, business_unit_id))',
            v_table || '_scope_policy', v_table
        );
    END LOOP;
END
$rls$;

GRANT USAGE ON SCHEMA revenue_assurance TO powerops_provisioner WITH GRANT OPTION;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA revenue_assurance
    TO powerops_provisioner WITH GRANT OPTION;

-- The shared scope provisioner may grant UPDATE on operational tables. This
-- trigger ensures audit evidence remains append-only for every runtime role.
CREATE OR REPLACE FUNCTION revenue_assurance.reject_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, revenue_assurance
AS $function$
BEGIN
    RAISE EXCEPTION 'revenue assurance evidence records are append-only'
        USING ERRCODE = '42501';
END
$function$;

REVOKE ALL ON FUNCTION revenue_assurance.reject_audit_mutation() FROM PUBLIC;
CREATE TRIGGER audit_events_no_update
    BEFORE UPDATE OR DELETE ON revenue_assurance.audit_events
    FOR EACH ROW EXECUTE FUNCTION revenue_assurance.reject_audit_mutation();

CREATE TRIGGER case_decisions_no_update
    BEFORE UPDATE OR DELETE ON revenue_assurance.case_decisions
    FOR EACH ROW EXECUTE FUNCTION revenue_assurance.reject_audit_mutation();

CREATE TRIGGER recovery_outcomes_no_update
    BEFORE UPDATE OR DELETE ON revenue_assurance.recovery_outcomes
    FOR EACH ROW EXECUTE FUNCTION revenue_assurance.reject_audit_mutation();


-- Explicitly extend the approved runtime identity after a new domain schema is
-- installed. This function grants access only to an active, database-bound
-- login identity; it does not accept caller-supplied tenant or BU identifiers.
CREATE OR REPLACE FUNCTION powerops_security.grant_revenue_assurance_access(
    p_role_name name
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
    IF p_role_name IS NULL
       OR length(p_role_name::text) > 63
       OR p_role_name::text !~ '^pwr_[a-z0-9_]{1,40}$' THEN
        RAISE EXCEPTION 'runtime role name is outside the approved format'
            USING ERRCODE = '22023';
    END IF;

    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci
     WHERE ci.singleton;

    SELECT binding.role_oid INTO STRICT v_role_oid
      FROM powerops_security.role_scope_binding AS binding
      JOIN pg_catalog.pg_roles AS runtime_role
        ON runtime_role.oid = binding.role_oid
       AND runtime_role.rolname = binding.role_name
     WHERE binding.cluster_id = v_cluster_id
       AND binding.role_name = p_role_name
       AND binding.active
       AND binding.scope_kind = 'business_unit'
       AND binding.business_unit_id IS NOT NULL
       AND runtime_role.rolcanlogin
       AND NOT runtime_role.rolsuper
       AND NOT runtime_role.rolcreatedb
       AND NOT runtime_role.rolcreaterole
       AND NOT runtime_role.rolinherit
       AND NOT runtime_role.rolreplication
       AND NOT runtime_role.rolbypassrls;

    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members AS membership
         WHERE membership.member = v_role_oid OR membership.roleid = v_role_oid
    ) THEN
        RAISE EXCEPTION 'runtime identity with role memberships cannot receive domain access'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1 FROM powerops_security.retired_role_identity AS retired
         WHERE retired.cluster_id = v_cluster_id
           AND (retired.role_oid = v_role_oid OR retired.role_name = p_role_name)
    ) THEN
        RAISE EXCEPTION 'retired runtime identity cannot receive domain access'
            USING ERRCODE = '42501';
    END IF;

    EXECUTE pg_catalog.format(
        'GRANT USAGE ON SCHEMA revenue_assurance TO %I', p_role_name
    );
    EXECUTE pg_catalog.format(
        'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA revenue_assurance TO %I',
        p_role_name
    );
END
$function$;

ALTER FUNCTION powerops_security.grant_revenue_assurance_access(name)
    OWNER TO powerops_provisioner;
REVOKE ALL ON FUNCTION powerops_security.grant_revenue_assurance_access(name)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.grant_revenue_assurance_access(name)
    TO powerops_provisioner;

COMMIT;
 THEN
        RAISE EXCEPTION 'runtime role name is outside the approved format'
            USING ERRCODE = '22023';
    END IF;

    SELECT ci.cluster_id INTO STRICT v_cluster_id
      FROM powerops_security.cluster_identity AS ci
     WHERE ci.singleton;

    SELECT binding.role_oid INTO STRICT v_role_oid
      FROM powerops_security.role_scope_binding AS binding
      JOIN pg_catalog.pg_roles AS runtime_role
        ON runtime_role.oid = binding.role_oid
       AND runtime_role.rolname = binding.role_name
     WHERE binding.cluster_id = v_cluster_id
       AND binding.role_name = p_role_name
       AND binding.active
       AND runtime_role.rolcanlogin
       AND NOT runtime_role.rolsuper
       AND NOT runtime_role.rolcreatedb
       AND NOT runtime_role.rolcreaterole
       AND NOT runtime_role.rolinherit
       AND NOT runtime_role.rolreplication
       AND NOT runtime_role.rolbypassrls;

    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members AS membership
         WHERE membership.member = v_role_oid OR membership.roleid = v_role_oid
    ) THEN
        RAISE EXCEPTION 'runtime identity with role memberships cannot receive domain access'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1 FROM powerops_security.retired_role_identity AS retired
         WHERE retired.cluster_id = v_cluster_id
           AND (retired.role_oid = v_role_oid OR retired.role_name = p_role_name)
    ) THEN
        RAISE EXCEPTION 'retired runtime identity cannot receive domain access'
            USING ERRCODE = '42501';
    END IF;

    EXECUTE pg_catalog.format(
        'GRANT USAGE ON SCHEMA revenue_assurance TO %I', p_role_name
    );
    EXECUTE pg_catalog.format(
        'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA revenue_assurance TO %I',
        p_role_name
    );
END
$function$;

ALTER FUNCTION powerops_security.grant_revenue_assurance_access(name)
    OWNER TO powerops_provisioner;
REVOKE ALL ON FUNCTION powerops_security.grant_revenue_assurance_access(name)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION powerops_security.grant_revenue_assurance_access(name)
    TO powerops_provisioner;

COMMIT;
