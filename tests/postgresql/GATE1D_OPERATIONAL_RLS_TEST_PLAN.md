# Gate 1D — operational RLS adversarial PostgreSQL test plan

**Execution status:** NOT TESTED. This document is a test specification, not evidence of execution.

Run against a disposable instance of the exact supported PostgreSQL version after migrations 0001–0005. Capture PostgreSQL version, migration logs, SQLSTATEs, role attributes, query results and exit codes. Connect using distinct actual login roles, not SET ROLE from a superuser.

## Fixture identities and rows
- Tenant A, business units A1 and A2.
- Tenant B, business unit B1.
- Runtime logins: tenant-A, BU-A1, BU-A2 and tenant-B.
- Seed one business unit, feeder, transformer, outage and energy reconciliation row in each scope.
- Use UUIDs and clearly synthetic source classifications. Do not use real utility identifiers.

## Required positive tests
1. Tenant-A can read and insert/update rows for A1 and A2.
2. BU-A1 can read and insert/update only A1 rows.
3. BU-A2 can read and insert/update only A2 rows.
4. Tenant-B can read and insert/update only B1 rows.
5. All normal writes preserve valid same-scope composite foreign keys.

## Required negative tests
1. BU-A1 cannot SELECT, UPDATE or insert rows scoped to A2 or B1.
2. Tenant-A cannot SELECT, UPDATE or insert rows scoped to B1.
3. Attempt to UPDATE a visible A1 row so its tenant_id or business_unit_id changes to A2/B1; expect RLS WITH CHECK rejection.
4. Attempt direct insert of a row with NULL tenant_id or business_unit_id; expect NOT NULL rejection.
5. Attempt to attach a transformer, outage or energy row to a feeder in another BU or tenant; expect composite-FK rejection.
6. Attempt cross-scope references to business_units; record whether PostgreSQL FK error details expose existence and assess as a possible information side channel.
7. Runtime logins cannot DELETE, TRUNCATE, ALTER, DROP, CREATE objects, create policies, disable RLS, grant privileges or assume another role.
8. Unknown, inactive and retired identities fail closed through the Gate 1A resolver.
9. Verify no runtime role has SUPERUSER, BYPASSRLS, CREATEROLE, CREATEDB, REPLICATION, INHERIT or role memberships.
10. Verify runtime roles have no privileges on security metadata tables other than the explicitly granted resolver/predicate execution path.

## Bypass and lifecycle tests
- Table owner with FORCE ROW LEVEL SECURITY; verify policy applies.
- Superuser and BYPASSRLS tests as explicit administrator trust-boundary demonstrations, not runtime acceptance.
- Views, SECURITY DEFINER functions, materialized views, partitions and background jobs.
- Prepared statements, connection pooling, concurrent sessions, credential rotation and retirement fencing.
- Provisioning failure injection at every step: no orphan role, binding, grant or login may remain after rollback.
- Verify BU provisioning workflow independently validates and authorizes the tenant/BU tuple before calling the SECURITY DEFINER provisioning function.
- Verify a future table added to the schema cannot silently ship without RLS, policy, grant review and CI coverage.

## Acceptance evidence
Attach exact migration output, test script and result, PostgreSQL version, exact commit SHA, CI run URL, independent reviewer identity/report, and remediation for every failure. A test plan or static SQL review is not a PASS.
