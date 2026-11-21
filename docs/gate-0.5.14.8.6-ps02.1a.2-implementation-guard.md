# PS-02.1A.2 — implementation guard and corrected migration prerequisites

Status: **implementation blocked pending a complete per-session identity migration design**.

Repository: `ooluboyede/cephas-ai-powerops`  
Branch: `security/revenue-assurance-gate-0.1`  
PR: #21  
Baseline reviewed: `fc8e6d03d0f1f6adfac09f2c98de64c1ff909af4`

## Safety correction

The CI workflow no longer applies `migrations/postgresql/0013_exact_human_session_backend_registry.sql`.

Migration 0013 is an unaccepted implementation attempt. Its session binding `role_oid` foreign key points directly to `human_actor_binding(cluster_id, role_oid)`, and its provisioner expects an existing actor login. That is incompatible with the required one-login-role-per-session model. Leaving it in the PostgreSQL matrix would execute a schema that does not establish the required UUID-to-dedicated-login identity.

This workflow change does not repair or validate migration 0013. Do not apply migration 0013 to customer databases.

## Source-level requirements confirmed

The following existing contracts were inspected:

- `0002_scope_identity.sql`: `role_scope_binding` is keyed by cluster and role OID; `resolve_authenticated_scope()` resolves `session_user` to that scope.
- `0003_scope_login_lifecycle.sql`: controlled provisioning creates a NOLOGIN role, binds scope, grants scope resolution, verifies role attributes and memberships, activates the binding, and makes LOGIN the final state transition.
- `0010_human_actor_identity_foundation.sql`: `human_actor_binding` has one actor row per actor/scope and its `role_oid` currently represents the actor login.
- `0011_human_finance_entitlements.sql`: finance maker/verifier entitlements live on the actor binding and must remain authoritative there.
- `0012_database_derived_finance_actors.sql`: maker/verifier and audit triggers call `resolve_authenticated_human_actor_v2()`; the audit trigger currently detects human identities by direct actor-role OID.
- `DatabaseSessionBroker.issue_session()`: currently resolves an actor's existing `database_role`, uses it as the certificate identity, and only then creates a new session UUID.
- `PsycopgHumanSessionConnector`: verifies the role and certificate but does not register the session UUID with PostgreSQL before yielding the connection.

## Required corrected migration

The next SQL implementation must be additive and fail closed:

1. Introduce a protected immutable mapping from a unique session role OID to the existing actor role OID and session UUID. Do not weaken the actor uniqueness constraint or duplicate actor entitlements.
2. Provision a fresh non-reused role for each session using the established NOLOGIN-first lifecycle. Derive issuer, subject, tenant, BU and finance entitlements from the locked actor row; never accept those values from the broker/API as authoritative.
3. Ensure the role is mapped to the actor and BU scope before LOGIN becomes usable. The certificate CN and stored credential role must identify this exact session role.
4. Change the human actor resolver to resolve authenticated session role → actor binding → actor entitlements, while preserving the intended non-human service-role behavior.
5. Update the audit-actor trigger's human-role detection to recognize session-role bindings, not just actor-role OIDs.
6. Implement exact-session retirement and permanent role-name/OID tombstones. Actor-wide revocation must enumerate and retire all session roles belonging to that actor.
7. Keep session-control privileges separate from the general provisioner and application roles; document and test the customer DBA privilege model.
8. Add PostgreSQL 14–17 tests for concurrent sessions for one actor, cross-actor/session substitution, expired/revoked actor, role-name/OID reuse, role escalation, resolver/finance-entitlement integrity, admission-vs-revocation races, and exact backend termination.
9. Integrate the broker and connector only after the SQL identity contract is implemented and tested.

## Validation and disposition

- This change is a CI safety guard and implementation prerequisite record only.
- No corrected session-role migration, broker provisioning adapter, connector registration, or PostgreSQL backend revocation is implemented here.
- No tests or workflow runs are claimed for this change.
- Gate PS-02.1A.2 is **not accepted**; PS-02 remains unaccepted.
- PR #21 must remain draft and unmerged.
