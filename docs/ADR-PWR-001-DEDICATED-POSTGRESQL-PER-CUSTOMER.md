# ADR-PWR-001 — Dedicated PostgreSQL cluster per utility customer

- **Status:** OWNER-APPROVED REFERENCE DEFAULT; CUSTOMER DEPLOYMENT APPROVAL STILL REQUIRED
- **Decision date:** 2026-11-13
- **Decision authority:** CEPHAS product owner approval recorded in the engineering conversation on 2026-11-13
- **Applies to:** PowerOps 0.1.1 reference architecture; IBEDC-first PoV design and subsequent utility-customer deployments
- **Decision scope:** architecture default only; this does not approve a live IBEDC deployment, customer network connection, production data, or production operations.

## Context

PowerOps is a customer-hosted utility intelligence platform. Customer isolation must not depend solely on application checks or caller-supplied tenant identifiers. The 0.1.1 security contract requires database identities bound to explicit tenant/business-unit scopes, protected role-to-scope mapping, PostgreSQL RLS, bounded pools, and fail-closed behavior.

## Decision

Use a **dedicated PostgreSQL cluster or independently administered PostgreSQL instance for each utility customer** as the default reference topology.

For IBEDC, the target topology is one IBEDC-controlled cluster/instance boundary for the IBEDC PowerOps deployment. A separate cluster/instance is required for each other utility customer. Staging and production must be separately isolated.

Within each customer cluster:
- Use distinct scope-bound PostgreSQL login identities; never use one shared cross-tenant or cross-business-unit runtime login.
- Derive effective database scope from authenticated `session_user` mapped through protected provisioning-owned metadata.
- Enforce row-level policies and composite tenant/business-unit integrity constraints where applicable.
- Keep migration/provisioning authority separate from runtime identities.
- Fail closed on unknown, stale, disabled, revoked, ambiguous, or unmapped identities.
- Do not expose database credentials, connection handles, or arbitrary SQL execution to untrusted callers.
- Apply the contract's protected transaction wrapper and synchronous durability rules to fence/retirement operations.

## Alternatives considered

1. **Shared database with RLS across customers:** rejected as the default because it shares more database-level blast radius and increases the consequences of a privilege, policy, or configuration error.
2. **Separate databases in one PostgreSQL cluster:** rejected as the default because cluster-wide roles, superuser/administrative authority, extensions, resource pressure, backup/restore and cluster compromise remain shared boundaries.
3. **Dedicated cluster/independently administered instance per customer:** selected because it creates the clearest customer-level administrative, credential, backup/restore, and failure-isolation boundary.

The selected topology does not remove the need for scope-bound database identities and RLS inside each customer deployment.

## Consequences and controls

- Higher infrastructure and operational cost per utility customer.
- Separate monitoring, patching, backup, restore, key/credential rotation, capacity planning, and disaster-recovery procedures per customer.
- Cross-customer analytics must use an explicitly approved export/aggregation boundary; no shared runtime database is implied.
- Customer-specific PostgreSQL version, HA/quorum topology, RTO/RPO, pooler, workload sizing, backup custodian, and operations owners remain deployment inputs and must be approved before Gate 0 closes.
- Any exception to this default requires a separate threat model, written rationale, customer approval, independent security review, and an updated ADR.

## Release boundary

This ADR approves the **reference architecture default only**. It does not close Gate 0 or any runtime security gate. It does not prove RLS, role mapping, identity validation, revocation, fence linearizability, synchronous failover durability, backup recovery, or deployment conformance. It does not authorize production deployment, customer production data, live IBEDC integrations, SCADA/DMS connectivity, dispatch, switching, protection operations, or operational activation.

## Acceptance evidence required before deployment

- Approved customer deployment profile with exact PostgreSQL build and HA/quorum settings.
- Evidence that each customer has a distinct cluster/instance identity and independently administered boundary.
- Separate staging/production evidence.
- Role-to-scope inventory and privilege/RLS audit.
- Adversarial cross-scope tests against real PostgreSQL.
- Backup/restore and failover evidence, including former-primary fencing and acknowledged fence-commit durability.
- Independent implementation/security review.
