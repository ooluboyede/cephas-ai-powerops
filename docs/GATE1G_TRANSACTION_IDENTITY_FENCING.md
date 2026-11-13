# Gate 1G — transaction and identity-fencing validation

**Status: implementation submitted; execution evidence pending. Gate 1G is NOT PASSED.**

Gate 1G extends the disposable Gate 1F PostgreSQL fixture. It makes no customer deployment or data changes.

## Added assertions
- Invalid provisioning input raises the expected validation error and leaves no PostgreSQL role, scope binding, or tombstone behind.
- Runtime logins have no direct or transitive PostgreSQL role-membership path.
- The controlled retirement function disables login, deactivates the scope binding, and records a permanent role-OID/name tombstone.

## Run
```bash
bash tests/postgresql/run_gate1g.sh
```

The script first executes Gate 1E and Gate 1F, then Gate 1G checks. Use only the disposable CI PostgreSQL service.

## Important limitations / NOT TESTED
- The invalid-input case validates precondition rollback, not failure injection after CREATE ROLE or after partial grants.
- Existing authenticated sessions are not terminated by PostgreSQL NOLOGIN; pool eviction and active-session termination remain operational requirements and are not proven here.
- Credential rotation, pool reuse, transaction-pooling semantics, and role switching are not tested.
- Table-owner/FORCE RLS, superuser/BYPASSRLS, views, SECURITY DEFINER application paths, partitions, triggers, background workers and future-table default privileges remain untested.
- Foreign-key side-channel behaviour and clone/restore fencing remain untested.
- No independent PostgreSQL security review is included.

## Acceptance
Gate 1G is not accepted until exact-head CI runs pass on PostgreSQL 14–17, logs and SQLSTATEs are inspected, and an independent PostgreSQL security reviewer signs off. Do not infer production readiness from a green test matrix alone.
