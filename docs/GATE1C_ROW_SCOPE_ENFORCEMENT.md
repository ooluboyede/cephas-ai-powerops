# Gate 1C — authenticated row-scope enforcement primitive

**Status:** draft implementation; not executed against PostgreSQL; no operational-table RLS policy has yet been applied or passed.

## Repository inspection finding
The existing reviewed PowerOps security PRs establish the cluster identity, role-to-scope mapping and lifecycle functions. The inspected changes do not establish an operational PostgreSQL schema for feeder, transformer, outage or energy records. This gate therefore does not invent those tables or claim row-level isolation on them.

## What this gate adds
- `powerops_security.row_scope_permits(tenant_id, business_unit_id)`, a SECURITY INVOKER predicate that resolves the caller's authenticated `session_user` through the Gate 1A resolver.
- Tenant-scoped logins may access rows belonging to their tenant across its business units.
- Business-unit-scoped logins may access only rows matching both their tenant and their bound business-unit UUID.
- NULL or non-matching row scope values do not pass the predicate.
- PUBLIC execution is revoked.
- The controlled provisioner receives grant option and the Gate 1B provisioning function is replaced so newly provisioned runtime roles receive EXECUTE on the resolver and row predicate before LOGIN is enabled.

## Required row policy shape
See `migrations/postgresql/templates/rls_policy_template.sql`. For every real operational table:
1. Require non-null tenant and business-unit identifiers.
2. Enforce the BU-to-tenant relationship with a composite FK or equivalent database constraint.
3. Enable and FORCE RLS.
4. Apply both USING and WITH CHECK predicates.
5. Grant only required table/column privileges to runtime roles.
6. Verify table owners, superusers, BYPASSRLS roles, views, materialized views, SECURITY DEFINER functions, partitions, foreign tables and background jobs cannot bypass the intended boundary.

The template's `app_schema.actual_operational_table` is a deliberate placeholder, not an existing table.

## Security semantics
- The predicate is SECURITY INVOKER: it does not elevate the caller to the resolver owner.
- It accepts row keys, not a requested tenant scope. The trusted scope still comes only from the authenticated database role mapping.
- Tenant scope sees all business-unit rows for its tenant; BU scope sees only its exact BU within that tenant.
- RLS is row filtering, not an access grant. Ordinary SQL privileges remain separately required.
- This does not defend against PostgreSQL superusers, a compromised cluster administrator, unsafe privileged functions, or a role granted BYPASSRLS. Those are separate administrative trust boundaries.

## Known Gate 1C limitations
- Migrations 0001–0004 have not been run against PostgreSQL in this environment.
- No real operational tables were available in the inspected PR diffs; therefore no table policy is yet attached.
- No adversarial SQL tests or CI evidence exist for this gate.
- Existing roles provisioned before this migration do not automatically receive the new predicate EXECUTE grant; they require controlled, audited grant reconciliation before RLS is enabled.
- Existing Gate 1B provisioning and retirement functions remain subject to independent review, including function ownership and grant-option verification.
- Pooling must preserve the authenticated database login identity. A shared pool login would collapse distinct scope identities and is prohibited by the reference model.
- A SECURITY DEFINER application function, owner bypass, superuser, BYPASSRLS role, partition routing error or unprotected view may bypass the intended policy unless specifically audited.

## Acceptance tests required
- Apply migrations 0001–0004 to the exact supported PostgreSQL build and capture version/output/exit codes.
- Provision tenant A, BU A1, BU A2 and tenant B identities using real PostgreSQL login sessions.
- Build disposable test tables with NOT NULL tenant_id/business_unit_id and a valid composite BU-to-tenant FK; attach ENABLE/FORCE RLS and both USING/WITH CHECK predicates.
- Verify tenant A reads/writes A1 and A2; BU A1 reads/writes only A1; BU A1 cannot read, insert, update or delete A2 or tenant B; tenant B cannot access tenant A.
- Attempt cross-scope INSERT and UPDATE including changing tenant_id or business_unit_id; expect denial.
- Verify unknown, inactive and retired identities fail closed.
- Verify runtime roles cannot disable RLS, alter policies, assume another role, create privileged functions or access security metadata directly.
- Test prepared statements, transaction pooling/session pooling, connection reuse, concurrent sessions and role switching.
- Test table owner, superuser, BYPASSRLS, views, SECURITY DEFINER functions, partitions and background-job access paths.
- Reconcile pre-existing runtime roles with the new predicate grant before activation.
- Obtain exact-head CI and independent PostgreSQL security review.

## Gate decision
**PARTIALLY IMPLEMENTED / NOT PASSED / NOT PRODUCTION-READY.** The reusable row-scope predicate and provisioning grant path are drafted. Actual operational-table RLS and adversarial PostgreSQL evidence remain outstanding.
