# PowerOps Revenue Assurance Gate 0.2 — scoped connection lifecycle

## Objective

Replace per-operation TCP connection creation with a bounded, reusable PostgreSQL pool without weakening the Gate 1 tenant/business-unit boundary or Gate 0.1 authenticated-scope checks.

## Isolation invariant

- One PowerOps application service instance is configured with exactly one BU-scoped PostgreSQL login and owns exactly one pool.
- Never place credentials for multiple tenants or business units in the same pool.
- Resolve `powerops_security.resolve_authenticated_scope()` on every checkout and compare both tenant and business-unit IDs with the verified OIDC principal before any domain query.
- A scope mismatch returns 403, rolls back the checkout transaction, and does not yield the connection to application code.
- PostgreSQL RLS and least-privilege grants remain the final data boundary; application checks do not replace them.

## Pool behavior

- Bounded pool defaults: minimum 1, maximum 8 connections, 5-second checkout timeout.
- Pool creation is lazy so liveness can operate when PostgreSQL is unavailable.
- Every checkout wraps scope verification and the repository operation in a transaction. Success commits; any exception rolls back before the connection is returned.
- Pool exhaustion or connection establishment failure fails closed with HTTP 503.
- Process shutdown drains the application-owned pool.
- Pool size and timeout can be configured with `DATABASE_POOL_MIN_SIZE`, `DATABASE_POOL_MAX_SIZE` and `DATABASE_POOL_TIMEOUT_SECONDS`.

## Credential rotation contract

`PostgresRevenueAssuranceRepository.rotate_credentials(new_dsn, scope)` creates a replacement pool, verifies that the replacement login resolves to the expected tenant and business unit, and only then atomically makes it the pool for new checkouts. The previous pool is drained after the swap so already-borrowed connections can finish.

A failed replacement or scope mismatch leaves the active pool unchanged. Secret-manager SDK integration and scheduled rotation orchestration are deliberately provider-neutral and are not claimed as implemented: an operator-controlled secret provider must supply the new DSN to this method. Never log or expose DSNs.

## Deployment topology

For multiple business units, deploy separate service instances (or independently isolated workers) with distinct BU-scoped credentials and distinct pool objects. Do not implement a shared cross-BU credential pool or choose a DSN from a caller-supplied tenant/BU header. A future multiplexed architecture would require a separately reviewed pool-per-identity registry with hard isolation, bounded cardinality and lifecycle controls; it is not part of this gate.

## Validation added

- Checkout resolves and checks scope before yielding a connection.
- Scope mismatch rolls back and returns the connection.
- Failed credential rotation does not replace the active pool.
- Successful rotation validates the replacement identity, swaps pools, and drains the old pool.
- Existing PostgreSQL repository integration tests continue to exercise the repository through the new pool.

## Explicit limitations

- GitHub Actions minutes/payment access are unavailable. During branch updates, automatic push/pull-request events started several workflows before triggers were paused; all affected runs ended with zero job steps. No tests or build commands executed.
- The two relevant security workflows are now restricted to manual `workflow_dispatch` triggers. Re-enable/dispatch them only after Actions minutes are restored.
- No Python, lint, type-check, or live PostgreSQL test result is claimed until the workflows can execute.
- No cloud secret-manager adapter, automated rotation scheduler, PgBouncer/managed-pooler validation, HA/failover test, customer identity provider, customer dataset, or production certification is included.
- The pool is per service instance and per BU login; multi-BU multiplexing is intentionally unsupported.
