# Gate 1E — executable PostgreSQL validation

**Status: harness and CI workflow submitted; execution evidence pending. This gate is NOT PASSED.**

## Added artifacts
- `tests/postgresql/run_gate1e.sh`: applies PostgreSQL migrations 0001–0005 to a disposable database, creates synthetic tenant A (BU A1/A2) and tenant B (BU B1), provisions four separate runtime login identities through the scope-provisioning function, and tests visibility using actual database connections.
- `.github/workflows/postgresql-security.yml`: PostgreSQL 14, 15, 16 and 17 matrix.

## Assertions currently automated
- Tenant-A sees both of its business-unit feeder rows, not tenant-B.
- BU-A1 sees only its own feeder row.
- BU-A2 sees only its own feeder row.
- Tenant-B sees only its own feeder row.
- BU-A1 cross-BU insert is rejected by RLS WITH CHECK.
- BU-A1 attempt to change an A1 row into A2 scope is rejected.
- Runtime DELETE is denied by database privileges.
- Runtime role flags are checked for LOGIN=true and SUPERUSER, CREATEDB, CREATEROLE, INHERIT, REPLICATION and BYPASSRLS=false.

## Deliberate limitations
This is a first executable smoke suite, not the complete adversarial plan. It does not yet prove:
- positive write behaviour for every table and scope;
- tenant-A cross-tenant insert/update denial;
- role membership and effective ACL closure across all objects;
- resolver fail-closed cases, retired identities or session/pool fencing;
- table owner, superuser/BYPASSRLS, view, SECURITY DEFINER, partition and background-job paths;
- provisioning rollback/failure injection or FK side-channel behaviour.

The test harness uses a disposable CI password only. It must never be reused in a customer environment.

## Acceptance
The CI workflow must execute against all declared PostgreSQL versions, and logs/results must be reviewed. Fix any migration, test or compatibility failures before marking PASS. Independent PostgreSQL security review remains mandatory. A green smoke test alone does not authorize customer data ingestion or production use.
