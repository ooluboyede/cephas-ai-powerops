# PowerOps Revenue Assurance Gate 0.3.3 — Pool Health Telemetry

## Objective

Add safe operational visibility into the BU-scoped PostgreSQL connection pool without exposing credentials, tenant identifiers, business-unit identifiers, or customer records.

## Implemented in this gate

- `ScopedConnectionPool.health_snapshot()` returns lifecycle state, active and cumulative checkout counts, consecutive checkout failures, last success/failure timestamps, failure exception class, successful rotation count, and configured maximum pool size.
- The pool tracks active borrowers and decrements the count even when application work or connection return raises.
- Successful checkouts clear the consecutive checkout-failure counter. A successful credential-pool swap increments the rotation counter and resets checkout failure state.
- `PostgresRevenueAssuranceRepository.pool_health()` exposes the pool snapshot to the application layer.
- `GET /health/pool` exposes only non-secret pool telemetry and returns HTTP 503 when the BU-scoped repository is not configured.
- A unit test covers uninitialized, active, released, rotated, and closed lifecycle states, including checks that DSN and tenant identifiers are not returned.

## Recovery semantics and limitations

- This gate adds observability, not automatic reconnect loops, retries, exponential backoff, or a background supervisor.
- A failed checkout remains a 503 to the caller. A subsequent request may succeed through the underlying psycopg pool's own behavior; no application-level retry is performed.
- Credential rotation remains explicitly triggered with an immutable version. This gate does not schedule rotation, create/revoke credentials, or automatically roll back a successful pool swap.
- Pool health is process-local telemetry. It is not a substitute for customer SIEM, metrics aggregation, alerting, or durable audit storage.
- `GET /health/pool` must be restricted to the customer's internal monitoring network or protected by the deployment's ingress policy. It is not intended as a public internet endpoint.
- GitHub Actions remain manual-dispatch only while the user's Actions capacity/payment issue is unresolved. Tests are authored but not executed in this environment.

## Required validation before promotion

- Run the complete unit suite and lint/type checks when CI capacity is restored.
- Run PostgreSQL 14–17 integration tests with a real BU-scoped login.
- Exercise pool exhaustion, connection loss, database restart, concurrent checkout, rotation during load, close with borrowers, and failure-audit delivery.
- Verify health endpoint ingress restrictions in the customer deployment.
- Obtain independent security review before removing draft status or merging.
