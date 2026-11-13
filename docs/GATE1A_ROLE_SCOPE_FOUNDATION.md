# Gate 1A — role identity and scope foundation

**Status:** implementation draft; not security-gate evidence or production-ready.

## Files
- `migrations/postgresql/0001_bootstrap_roles.sql`: creates and checks the non-login provisioning and resolver principals.
- `migrations/postgresql/0002_scope_identity.sql`: creates cluster identity, scope bindings, retired-identity tombstones and the authenticated scope resolver.

## Security properties intended by this slice
- The effective login is sourced from PostgreSQL `session_user`, not `current_user` (which is the SECURITY DEFINER owner inside the function).
- The resolver obtains the role OID using the trusted `pg_catalog.pg_roles` catalog view and binds it to the provisioned cluster UUID and one explicit tenant or business-unit scope.
- Missing, non-login, retired, inactive, unmapped or non-unique identities fail closed.
- Runtime roles receive no direct table privileges. The resolver owner receives SELECT only on the three security metadata tables.
- Function execution is revoked from PUBLIC. Each runtime login must receive explicit schema USAGE and function EXECUTE grants from the controlled provisioner.
- Role-name and role-OID tombstones are represented in the schema to support the permanent non-reuse policy.

## Important limitations — deliberately not claimed as complete
1. This slice does not yet implement an atomic role-provisioning/deprovisioning service, credential rotation, pool eviction, session termination or interrupted-operation recovery.
2. The cluster UUID must be independently provisioned and bound to the actual cluster lifecycle. Clone/restore fencing and duplicate-active-cluster prevention remain open.
3. The resolver is not yet attached to protected application tables through RLS policies. Until those policies and real PostgreSQL adversarial tests exist, this function alone does not enforce row isolation.
4. The migration does not grant runtime execution automatically; grants are per approved scope login and must be produced by the controlled provisioning workflow.
5. The SECURITY DEFINER effective privilege inventory, hostile search_path/temporary-object tests, catalog resolution tests, tombstone restore tests and exact PostgreSQL build evidence remain mandatory.
6. The SQL has not been executed against a PostgreSQL server in this environment. It must be reviewed and run against the selected supported PostgreSQL build before any gate can pass.

## Required next acceptance tests
- Capture both `session_user` and `current_user` in a test-only controlled probe and prove the resolver uses the former.
- Valid mapped login resolves exactly one scope.
- Unknown, disabled, non-login, inactive and retired identities are denied.
- Runtime cannot SELECT/INSERT/UPDATE/DELETE/TRUNCATE security metadata or alter roles/memberships.
- PUBLIC cannot execute the resolver.
- Hostile `search_path` and temporary objects cannot shadow catalog or security objects.
- Role-name and role-OID tombstones survive backup/restore and are not removed by normal provisioning.
- No scope is returned if the cluster identity row is absent or ambiguous.

Do not enable production data, live IBEDC identity, integrations or operational commands on the basis of this draft.
