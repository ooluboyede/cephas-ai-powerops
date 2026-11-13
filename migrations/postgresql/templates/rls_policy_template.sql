-- TEMPLATE ONLY — adapt only after reviewing the actual operational table DDL.
-- Every protected row must carry NOT NULL tenant_id and business_unit_id UUIDs.
-- Enforce the BU-to-tenant relationship with an appropriate composite FK.
ALTER TABLE app_schema.actual_operational_table ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_schema.actual_operational_table FORCE ROW LEVEL SECURITY;

CREATE POLICY actual_operational_table_scope_policy
ON app_schema.actual_operational_table
FOR ALL
USING (
    powerops_security.row_scope_permits(tenant_id, business_unit_id)
)
WITH CHECK (
    powerops_security.row_scope_permits(tenant_id, business_unit_id)
);

-- Runtime roles must also have only the required table/column privileges.
-- RLS does not grant privileges and is not a substitute for least privilege.
-- Test as actual runtime logins, never as a superuser or BYPASSRLS role.
