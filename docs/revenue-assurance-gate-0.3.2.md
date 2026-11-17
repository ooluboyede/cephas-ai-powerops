# PowerOps Revenue Assurance Gate 0.3.2 — Version-Pinned Credential Rotation

## Objective

Add a controlled rotation coordinator that retrieves an explicit immutable secret version, asks the existing repository to validate and atomically replace its BU-scoped PostgreSQL pool, and records non-secret outcome metadata.

## Implemented

- `src/powerops/rotation.py` adds `CredentialRotationService`.
- The service is permanently bound at construction to one secret reference, tenant UUID, and business-unit UUID. These values cannot be supplied by an API caller during rotation.
- Rotation requires an explicit immutable version. Aliases such as latest/current and the development adapter's unversioned value are rejected.
- Provider-returned reference and version must exactly match the requested deployment-bound reference and version.
- Candidate credentials are passed only to the existing `repository.rotate_credentials()` path, which verifies the database login's tenant and business-unit identity before swapping the pool.
- The old pool remains the active pool if secret retrieval or replacement-pool validation fails (subject to the existing repository rotation contract).
- The service records only reference, provider name, version, tenant/BU IDs, timestamp, and outcome through a customer-owned audit sink. It never puts the DSN in audit metadata.
- A post-swap audit failure is surfaced as a distinct `CredentialRotationAuditError`: the pool has already changed, so operators must repair audit delivery rather than blindly retrying rotation.
- Concurrent calls on one service instance are serialized.

## Operational trigger boundary

This gate implements the rotation coordinator, not a background scheduler or a provider event subscription. A deployment-owned rotation trigger must call `rotate_to_version(immutable_version)` after a provider announces an approved version. Gate 0.3.3 will add health checks, retry/backoff policy and trigger lifecycle controls. No cloud provider SDK or scheduler is selected here.

## Required customer deployment configuration

- One provider reference per PowerOps service instance / BU-scoped database identity.
- Provider workload identity with read access to only that secret.
- Immutable version identifier supplied by the provider.
- A durable customer-owned audit sink for rotation events.
- A provider-specific rollback/overlap window so old credentials remain valid until the replacement pool is proven healthy and old borrowers are drained.

## Safety and limitations

- The coordinator does not expose an HTTP rotation endpoint. Rotation is an internal deployment operation; any future admin endpoint requires separate privileged authorization, step-up authentication, audit, and anti-CSRF protections.
- It does not schedule rotation, create credentials in PostgreSQL, revoke old credentials, or select a provider.
- The current repository's pool swap and drain behavior still needs real psycopg_pool concurrency/close validation.
- CI evidence before Gate 0.5.8: Revenue Assurance Gates 0.1–0.2 passed on PostgreSQL 14, 15, 16 and 17 (run 43919924737); PostgreSQL Security Gates 1E–1I passed on PostgreSQL 14–17 (run 43919417287). These runs predate the Gate 0.5.8 remediation and do not validate its new migration or tests. The remediation must be rerun through both workflows before merge.
- Production approval requires live provider adapter, workload identity, durable audit integration, PostgreSQL 14–17 tests, concurrency/failure-injection tests, and independent security review. PR #21 remains draft/unmerged pending these checks.

## Gate 0.5.8 recovery-verification rollout requirements

- Apply migration `0008_recovery_verification_separation.sql`, then `0009_recovery_verification_rollout.sql`.
- Migration 0009 grants the new table to every active, database-bound business-unit runtime identity by calling the hardened `powerops_security.grant_revenue_assurance_access()` function. It does not grant access to tenant-wide or retired identities.
- Migration 0009 intentionally stops if legacy `recovery_outcomes` rows still have `outcome='verified'`. The customer must reconcile those records before retrying; no verifier identity, reason, or evidence is fabricated.
- Duplicate verification attempts are returned as HTTP 409 while the database unique constraint remains the final concurrency control.
- PostgreSQL integration coverage must confirm that roles provisioned before migration 0008 receive the new table privileges and that duplicate verification returns a conflict.
