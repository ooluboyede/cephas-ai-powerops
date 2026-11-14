# Gate 1G — session identity, pool safety contract and retirement fencing

**Status: implementation submitted; execution evidence pending. Gate 1G is NOT PASSED.**

## Objective

Prove that database scope derives from the authenticated PostgreSQL login, not mutable application session state, and that retiring an identity requires both a login fence and explicit termination of existing sessions.

## Automated coverage

- A dedicated BU-scoped login observes only its assigned BU.
- Caller-controlled tenant/BU GUC values do not change the resolver-derived scope.
- A prepared statement executes under the same authenticated login and retains its RLS boundary.
- A runtime login cannot use SET ROLE to borrow another tenant's or BU's identity.
- A live test connection remains present after the retirement function fences new logins.
- The harness explicitly terminates that existing backend and verifies that it disappears.
- A retired NOLOGIN identity cannot establish a new connection.

## Connection-pool deployment contract

1. Use a distinct PostgreSQL login and independently bounded pool for each approved tenant/BU scope.
2. Never multiplex different scopes through a shared login and never use SET ROLE as the tenant-switching mechanism.
3. Do not trust tenant/BU GUCs, request headers, JWT claims or application-supplied SQL parameters as database identity.
4. On retirement or credential rotation, fence the login, terminate all existing sessions, evict the corresponding pool, verify zero sessions, then complete dependency cleanup.
5. Re-authenticate using a newly provisioned login after scope changes; do not repurpose a retired role name or OID.
6. Use transaction rollback and connection reset on every pool checkout/check-in; these are defense-in-depth, not substitutes for distinct login identities.

## Limitations

- CI uses direct libpq/psql connections. It does not prove behavior of PgBouncer, JDBC, ODBC, Npgsql, ORM pools, serverless proxies or customer-specific poolers.
- Prepared-statement coverage is same-session only; it does not simulate a pooler that changes backend/session mapping.
- The test explicitly terminates a backend after retirement. The retirement function itself only inserts a tombstone, deactivates the binding and sets NOLOGIN; it does not terminate sessions.
- PostgreSQL superusers and BYPASSRLS roles remain trusted cluster-administrator boundaries.
- No customer database, IBEDC integration, production deployment, SCADA/DMS command path or dispatch action is involved.

## Acceptance

1. Exact-head CI completes successfully on PostgreSQL 14–17 with full logs.
2. The test is repeated with supported production poolers and driver versions before customer deployment.
3. Independent PostgreSQL security review verifies role lifecycle, session termination, pool eviction and prepared statement behavior.
4. Keep this and all stacked security PRs draft/unmerged until the evidence and review are complete.
