# PostgreSQL Gate 1C test plan

This directory contains the required adversarial test contract. Tests must execute against a disposable instance of the exact supported PostgreSQL build and must connect as distinct non-superuser runtime login roles. Do not treat static SQL inspection as passing evidence.

## Fixture topology
- Tenant A with business units A1 and A2.
- Tenant B with business unit B1.
- Runtime identities: tenant-A, BU-A1, BU-A2, tenant-B.
- Protected test table: synthetic test-only records with NOT NULL tenant_id and business_unit_id and a composite FK to the fixture business-unit registry.
- Enable and FORCE RLS; apply both USING and WITH CHECK using the Gate 1C predicate.

## Required assertions
1. Tenant-A can read and write A1 and A2, but not B1.
2. BU-A1 can read and write A1 only; BU-A2 and tenant-B rows remain invisible.
3. BU-A1 cannot insert a row for A2 or B1.
4. BU-A1 cannot update an A1 row to A2 or B1 scope.
5. Tenant-A cannot insert or update a row into tenant B.
6. Unknown, inactive and retired identities cannot resolve a scope.
7. Runtime roles cannot change role attributes, memberships, table ownership, RLS state, policies or security metadata.
8. Connection reuse, prepared statements, transaction pooling and session pooling do not retain a prior identity's scope.
9. Table owner, superuser, BYPASSRLS, views, SECURITY DEFINER functions, partitions and background jobs are tested as separate bypass paths.
10. All negative tests assert SQLSTATE and record the exact role, statement and expected/actual outcome.

No test in this file is claimed to have been executed.
