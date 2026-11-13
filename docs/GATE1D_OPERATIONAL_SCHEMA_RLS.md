# Gate 1D — operational schema and forced row-level security

**Status:** implementation draft committed; PostgreSQL execution, exact-head CI, adversarial tests and independent review are pending. This is not a passed security gate.

## Why this gate exists
Gate 1C supplied an authenticated row-scope predicate but did not attach it to operational tables. The IBEDC synthetic PoV contract identifies four operational domains: feeders, transformers, outages and energy reconciliation. This gate establishes a minimal relational foundation for those entities and a business-unit registry.

## Added migration
`migrations/postgresql/0005_operational_schema_rls.sql` creates:
- `powerops_data.business_units`
- `powerops_data.feeders`
- `powerops_data.transformers`
- `powerops_data.outages`
- `powerops_data.energy_reconciliation`

Every row carries non-null `tenant_id` and `business_unit_id`. Composite foreign keys bind each operational record to a business unit and bind transformers, outages and energy reconciliation to a feeder in the same tenant and business unit. Outage restoration ordering and non-negative capacity/energy constraints are enforced in PostgreSQL.

All five tables receive ENABLE ROW LEVEL SECURITY, FORCE ROW LEVEL SECURITY, and a FOR ALL policy using the Gate 1C authenticated `row_scope_permits(tenant_id,business_unit_id)` predicate in both USING and WITH CHECK.

## Runtime privilege model
The provisioning function is extended to grant a newly provisioned runtime login:
- USAGE on `powerops_security` and `powerops_data`;
- EXECUTE on the authenticated scope resolver and row-scope predicate;
- SELECT, INSERT and UPDATE on the operational tables.

Runtime logins receive no DELETE, TRUNCATE, REFERENCES, TRIGGER, ownership, role membership, superuser or BYPASSRLS privilege. RLS still filters every granted row operation. The provisioner receives GRANT OPTION for the narrowly-scoped schema/table grants so it can delegate them within its SECURITY DEFINER lifecycle function.

The provisioning function deliberately does not query the FORCE-RLS business-unit table to validate a BU: an unscoped provisioner would be filtered by RLS. The deployment authority must independently approve/register the BU before provisioning a BU-scoped login. This control needs a separately audited provisioning workflow and is an explicit open item.

## Data semantics and limitations
- This schema is derived from the existing synthetic PoV data contract, not an IBEDC-approved production data model.
- Source classification is explicit: synthetic, measured, derived feature, model output or engineer-validated conclusion.
- The database stores source system, source record ID, observation/ingestion timestamps where applicable.
- Loading percentages and risk bands remain derived values and are not persisted as verified diagnoses by this migration.
- Energy gap is intentionally not stored as a loss classification.
- No ML feature store, model registry, customer connector, ingestion API, SCADA/DMS integration or control path is added.
- Runtime role provisioning requires the deployment authority to supply a valid tenant/BU scope tuple. Tenant and BU identifiers are not accepted from an end-user request as an authorization source.

## Mandatory validation
Run migrations 0001–0005, in order, on the exact supported PostgreSQL major/minor release. Then provision distinct tenant and BU runtime logins and execute the adversarial test plan in `tests/postgresql/GATE1D_OPERATIONAL_RLS_TEST_PLAN.md`. Tests must include cross-tenant and cross-BU reads, inserts, updates, composite-FK integrity, role privilege inspection, owner/BYPASSRLS/view/function/partition paths, and rollback/failure injection in provisioning.

## Gate decision
**IMPLEMENTED AS A DRAFT / NOT PASSED / NOT PRODUCTION-READY.** The migration and operational RLS policies are committed for review. No PostgreSQL execution, exact-head CI result or independent security approval is claimed. Customer data ingestion remains prohibited until all required security, data governance and customer-approval gates pass.
