-- PowerOps 0.1.1 Gate 1D — operational schema with forced tenant/BU RLS.
-- Apply after migrations 0001–0004 using the controlled cluster migration authority.
-- This is a first operational schema contract derived from the IBEDC synthetic PoV
-- entities; it is not evidence of a customer deployment or customer data ingestion.
BEGIN;

CREATE SCHEMA powerops_data;
REVOKE ALL ON SCHEMA powerops_data FROM PUBLIC;

CREATE TABLE powerops_data.business_units (
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    business_unit_code text NOT NULL CHECK (length(btrim(business_unit_code)) BETWEEN 1 AND 80),
    display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 160),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, business_unit_id),
    UNIQUE (tenant_id, business_unit_code)
);

CREATE TABLE powerops_data.feeders (
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    feeder_id uuid NOT NULL,
    feeder_code text NOT NULL CHECK (length(btrim(feeder_code)) BETWEEN 1 AND 80),
    display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 160),
    nominal_voltage_kv numeric(8,2) NOT NULL CHECK (nominal_voltage_kv > 0),
    rated_capacity_mw numeric(14,4) NOT NULL CHECK (rated_capacity_mw > 0),
    source_classification text NOT NULL CHECK (source_classification IN
        ('SYNTHETIC_NOT_CUSTOMER_DATA','MEASURED','DERIVED_FEATURE',
         'MODEL_OUTPUT','ENGINEER_VALIDATED_CONCLUSION')),
    source_system text NOT NULL CHECK (length(btrim(source_system)) BETWEEN 1 AND 120),
    source_record_id text,
    observed_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, business_unit_id, feeder_id),
    UNIQUE (tenant_id, business_unit_id, feeder_code),
    FOREIGN KEY (tenant_id, business_unit_id)
        REFERENCES powerops_data.business_units (tenant_id, business_unit_id)
);

CREATE TABLE powerops_data.transformers (
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    transformer_id uuid NOT NULL,
    feeder_id uuid NOT NULL,
    transformer_code text NOT NULL CHECK (length(btrim(transformer_code)) BETWEEN 1 AND 80),
    rated_capacity_kva numeric(14,2) NOT NULL CHECK (rated_capacity_kva > 0),
    source_classification text NOT NULL CHECK (source_classification IN
        ('SYNTHETIC_NOT_CUSTOMER_DATA','MEASURED','DERIVED_FEATURE',
         'MODEL_OUTPUT','ENGINEER_VALIDATED_CONCLUSION')),
    source_system text NOT NULL CHECK (length(btrim(source_system)) BETWEEN 1 AND 120),
    source_record_id text,
    observed_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, business_unit_id, transformer_id),
    UNIQUE (tenant_id, business_unit_id, transformer_code),
    FOREIGN KEY (tenant_id, business_unit_id)
        REFERENCES powerops_data.business_units (tenant_id, business_unit_id),
    FOREIGN KEY (tenant_id, business_unit_id, feeder_id)
        REFERENCES powerops_data.feeders (tenant_id, business_unit_id, feeder_id)
);

CREATE TABLE powerops_data.outages (
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    outage_id uuid NOT NULL,
    feeder_id uuid NOT NULL,
    started_at timestamptz NOT NULL,
    restored_at timestamptz,
    cause_code text NOT NULL CHECK (length(btrim(cause_code)) BETWEEN 1 AND 80),
    source_classification text NOT NULL CHECK (source_classification IN
        ('SYNTHETIC_NOT_CUSTOMER_DATA','MEASURED','DERIVED_FEATURE',
         'MODEL_OUTPUT','ENGINEER_VALIDATED_CONCLUSION')),
    source_system text NOT NULL CHECK (length(btrim(source_system)) BETWEEN 1 AND 120),
    source_record_id text,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, business_unit_id, outage_id),
    CHECK (restored_at IS NULL OR restored_at > started_at),
    FOREIGN KEY (tenant_id, business_unit_id)
        REFERENCES powerops_data.business_units (tenant_id, business_unit_id),
    FOREIGN KEY (tenant_id, business_unit_id, feeder_id)
        REFERENCES powerops_data.feeders (tenant_id, business_unit_id, feeder_id)
);

CREATE TABLE powerops_data.energy_reconciliation (
    tenant_id uuid NOT NULL,
    business_unit_id uuid NOT NULL,
    reconciliation_id uuid NOT NULL,
    feeder_id uuid NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    energy_input_mwh numeric(18,4) NOT NULL CHECK (energy_input_mwh >= 0),
    billed_energy_mwh numeric(18,4) NOT NULL CHECK (billed_energy_mwh >= 0),
    source_classification text NOT NULL CHECK (source_classification IN
        ('SYNTHETIC_NOT_CUSTOMER_DATA','MEASURED','DERIVED_FEATURE',
         'MODEL_OUTPUT','ENGINEER_VALIDATED_CONCLUSION')),
    source_system text NOT NULL CHECK (length(btrim(source_system)) BETWEEN 1 AND 120),
    source_record_id text,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, business_unit_id, reconciliation_id),
    CHECK (period_end > period_start),
    FOREIGN KEY (tenant_id, business_unit_id)
        REFERENCES powerops_data.business_units (tenant_id, business_unit_id),
    FOREIGN KEY (tenant_id, business_unit_id, feeder_id)
        REFERENCES powerops_data.feeders (tenant_id, business_unit_id, feeder_id)
);

CREATE INDEX feeders_scope_code_idx
    ON powerops_data.feeders (tenant_id, business_unit_id, feeder_code);
CREATE INDEX transformers_scope_feeder_idx
    ON powerops_data.transformers (tenant_id, business_unit_id, feeder_id);
CREATE INDEX outages_scope_started_idx
    ON powerops_data.outages (tenant_id, business_unit_id, started_at DESC);
CREATE INDEX energy_scope_period_idx
    ON powerops_data.energy_reconciliation
       (tenant_id, business_unit_id, feeder_id, period_start DESC);

-- FORCE RLS also subjects table owners to policies. Superusers and BYPASSRLS
-- remain cluster-administrator trust boundaries and must never be runtime roles.
DO $rls$
DECLARE
    v_table text;
BEGIN
    FOREACH v_table IN ARRAY ARRAY[
        'business_units', 'feeders', 'transformers', 'outages',
        'energy_reconciliation'
    ] LOOP
        EXECUTE pg_catalog.format(
            'ALTER TABLE powerops_data.%I ENABLE ROW LEVEL SECURITY', v_table
        );
        EXECUTE pg_catalog.format(
            'ALTER TABLE powerops_data.%I FORCE ROW LEVEL SECURITY', v_table
        );
        EXECUTE pg_catalog.format(
            'CREATE POLICY %I ON powerops_data.%I FOR ALL USING ' ||
            '(powerops_security.row_scope_permits(tenant_id, business_unit_id)) ' ||
            'WITH CHECK (powerops_security.row_scope_permits(tenant_id, business_unit_id))',
            v_table || '_scope_policy', v_table
        );
    END LOOP;
END
$rls$;

-- The provisioner must be able to delegate only these bounded privileges.
GRANT USAGE ON SCHEMA powerops_data TO powerops_provisioner WITH GRANT OPTION;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA powerops_data
    TO powerops_provisioner WITH GRANT OPTION;

-- Extend the controlled login provisioning path. Runtime roles receive no
-- DELETE, TRUNCATE, REFERENCES, TRIGGER, ownership or role-membership rights.
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
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = p_role_name
    ) OR EXISTS (
        SELECT 1 FROM powerops_security.role_scope_binding AS binding
         WHERE binding.cluster_id = v_cluster_id
           AND binding.role_name = p_role_name
    ) THEN
        RAISE EXCEPTION 'runtime role name exists or is permanently retired'
            USING ERRCODE = '23505';
    END IF;

    IF p_scope_kind = 'business_unit' AND NOT EXISTS (
        SELECT 1 FROM powerops_data.business_units AS bu
         WHERE bu.tenant_id = p_tenant_id
           AND bu.business_unit_id = p_business_unit_id
    ) THEN
        RAISE EXCEPTION 'business-unit scope is not registered for tenant'
            USING ERRCODE = '23503';
    END IF;

    EXECUTE pg_catalog.format(
        'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
        p_role_name
    );
    SELECT r.oid INTO STRICT v_role_oid
      FROM pg_catalog.pg_roles AS r WHERE r.rolname = p_role_name;

    IF EXISTS (
        SELECT 1 FROM powerops_security.retired_role_identity AS retired
         WHERE retired.cluster_id = v_cluster_id AND retired.role_oid = v_role_oid
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
    EXECUTE pg_catalog.format(
        'GRANT EXECUTE ON FUNCTION powerops_security.row_scope_permits(uuid, uuid) TO %I',
        p_role_name
    );
    EXECUTE pg_catalog.format(
        'GRANT USAGE ON SCHEMA powerops_data TO %I', p_role_name
    );
    EXECUTE pg_catalog.format(
        'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA powerops_data TO %I',
        p_role_name
    );

    SELECT * INTO STRICT v_role FROM pg_catalog.pg_roles WHERE oid = v_role_oid;
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
     WHERE cluster_id = v_cluster_id AND role_oid = v_role_oid AND NOT active;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'scope binding activation failed';
    END IF;
    EXECUTE pg_catalog.format('ALTER ROLE %I LOGIN', p_role_name);
    RETURN v_role_oid;
END
$function$;

ALTER FUNCTION powerops_security.provision_scope_login(name, uuid, text, uuid)
    OWNER TO powerops_provisioner;
REVOKE ALL ON FUNCTION powerops_security.provision_scope_login(name, uuid, text, uuid)
    FROM PUBLIC;

COMMIT;
