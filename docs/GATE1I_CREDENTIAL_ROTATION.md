# Gate 1I — credential rotation and stale-session fencing

**Status: implementation submitted; CI execution pending. Gate 1I is NOT PASSED.**

## Objective
Exercise a disposable credential rotation through PgBouncer without changing the database-authenticated tenant/business-unit identity. Verify that the previous secret stops authenticating after the pooler's auth-file reload, the replacement secret works, and old backend sessions are fenced.

## Test sequence
1. Provision a synthetic BU-scoped login and set a disposable initial PostgreSQL password.
2. Start PgBouncer in transaction mode with a private, mode-0600 auth file.
3. Confirm the initial credential authenticates and sees only its expected fixture row.
4. Change the PostgreSQL role password; atomically replace the PgBouncer auth file; issue PgBouncer `RELOAD` and `RECONNECT`.
5. Assert the old credential is rejected and the new credential authenticates with unchanged database-derived scope.
6. Terminate remaining PostgreSQL sessions for that role, request pool reconnection, and assert no backend session remains.

## Security boundaries
- Test secrets are disposable CI-only values. Production secrets must be generated, stored and rotated through the customer's approved secret manager; never commit them or place them in application configuration.
- Rotation must preserve the database role identity and its immutable tenant/BU binding. Do not repurpose one database login for another tenant or business unit.
- A successful auth-file reload does not prove that every client, replica, HA pooler, proxy or application pool has refreshed credentials.
- Session termination can interrupt in-flight work. Production rollout requires a coordinated drain, bounded retry, observability and rollback procedure.

## Not covered
Customer secret-manager APIs, HA/multi-node PgBouncer, simultaneous in-flight transactions, Kubernetes/cloud proxy pools, application-driver pools, failover, credential rotation at scale, or customer production deployment.

## Acceptance
1. Exact-head workflow runs Gates 1E–1I on PostgreSQL 14–17 with complete logs.
2. Confirm PgBouncer version and supported auth-file reload semantics.
3. Independently review auth-file permissions, atomic replacement, rotation order, RECONNECT semantics and session fencing.
4. Keep draft/unmerged until exact-head CI and independent review pass.

No customer data, IBEDC integration, SCADA/DMS control or dispatch action is introduced.
