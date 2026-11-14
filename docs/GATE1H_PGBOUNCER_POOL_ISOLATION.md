# Gate 1H — PgBouncer transaction-pool isolation

**Status: implementation submitted; CI execution pending. Gate 1H is NOT PASSED.**

## Objective

Exercise the PowerOps authenticated PostgreSQL scope model through a real PgBouncer transaction pool with a deliberately small backend pool, alternating distinct tenant/BU logins.

## Automated coverage

- Provision separate BU-scoped logins for Tenant A / BU A1 and Tenant B / BU B1.
- Start PgBouncer in transaction-pooling mode with a one-server pool.
- Alternate 12 rounds of connections for each identity, encouraging backend reuse.
- Assert every request sees its authenticated `session_user` and exactly its own one-row fixture.
- Attempt caller-controlled tenant GUC spoofing through the pool and assert that the row boundary does not change.
- Enable `DISCARD ALL` as the server reset query and `server_reset_query_always` for this disposable test.

## Security interpretation

A connection pool must not turn one database login into a multi-tenant identity switch. Separate login identities and independently bounded pools remain the required design. Session reset is defense-in-depth only; it does not authorize sharing one database login across tenants or business units.

## Limits / not covered

- This uses PgBouncer transaction mode only. It does not certify session mode, statement mode, PgBouncer versions other than the CI package, JDBC/ODBC/Npgsql/ORM pools, cloud database proxies, or serverless poolers.
- It does not test a customer production deployment, secret manager, credential rotation workflow, or live pool eviction on role retirement.
- It does not establish prepared-statement behavior through transaction pooling; protocol-level prepared statement support depends on PgBouncer version/configuration.
- Test credentials are disposable CI-only plaintext values, not production credential guidance.
- The fixture is synthetic; no utility customer data, IBEDC connection, SCADA/DMS control or dispatch path is involved.

## Acceptance

1. Exact-head CI executes Gates 1E–1H on PostgreSQL 14–17 and retains complete logs.
2. Pin and record the PgBouncer version used by CI; validate the customer-supported version separately.
3. Independently review pool configuration, auth-file handling, reset semantics, per-scope pool boundaries and retirement/eviction operations.
4. Keep the PR draft/unmerged until all evidence and review are complete.
