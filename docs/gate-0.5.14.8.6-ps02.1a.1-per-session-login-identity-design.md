# PS-02.1A.1 — Per-session PostgreSQL login identity provisioning

Status: implementation design; no migration or runtime code is implemented by this document.

## 1. Decision

Use a dedicated, non-reused PostgreSQL LOGIN role for every issued human database session. A session UUID must map to exactly one PostgreSQL role OID, and the authenticated `session_user` must resolve to that role. One human actor may have many concurrent session roles. The existing actor identity remains the source of truth for issuer, subject, tenant, BU and finance entitlements.

Do not weaken the existing actor/scope uniqueness constraints to create duplicate actor rows for each session. Introduce a separate session-to-actor binding.

## 2. Existing schema and broker constraints

Migration 0003 `provision_scope_login` creates a fresh role with NOLOGIN, no elevated attributes, no memberships, and a scope binding; it then activates the binding and changes the role to LOGIN in one transaction. It permanently rejects retired role names and records retired OIDs. This lifecycle is the appropriate foundation for a per-session login, subject to explicit review of privileges and its scope-binding semantics.

Migration 0010 `human_actor_binding` has primary key (cluster_id, role_oid) and unique (cluster_id, issuer, subject, tenant_id, business_unit_id). It is an actor-level binding, not a per-session table. `provision_human_actor_login` creates a role and inserts this actor binding. Calling it for each session would violate the actor uniqueness constraint and incorrectly duplicate actor authority.

The current broker's `IdentityDirectory.resolve` returns one pre-provisioned actor database role. `DatabaseSessionBroker.issue_session` reuses that role and generates a new UUID only after certificate issuance. This must change: session role provisioning must happen through a trusted customer control-plane adapter, and the returned role name/OID must be bound to the exact UUID before a certificate or lease is returned.

The current `resolve_authenticated_human_actor_v2()` resolves the actor directly by the authenticated role OID. It must be revised to resolve a session role first, then join its immutable session-actor binding to the existing actor row and re-check actor, scope, expiry and entitlement state. Every downstream finance authorization path must continue using database-derived values from that resolver, not token claims or client-supplied identifiers.

## 3. Proposed protected schema

Add a protected table such as `powerops_security.human_session_actor_binding` with:

- `cluster_id`;
- `session_role_oid` referencing the session role's `role_scope_binding`;
- `actor_role_oid` referencing the existing `human_actor_binding`;
- `session_id` unique and immutable;
- actor-derived tenant ID, BU ID, issuer and subject snapshots for consistency checks;
- creation and expiry metadata;
- active/revoked state and immutable revocation metadata.

Required constraints:
- Primary key (cluster_id, session_role_oid).
- Unique (cluster_id, session_id).
- Unique (cluster_id, session_role_oid, session_id) if useful for FK composition.
- Foreign keys to both the session role scope row and actor binding row.
- No direct INSERT/UPDATE/DELETE for API runtime, human roles, or the general scope resolver.
- Enforce one active role per session UUID and never reuse a role name or OID after retirement.
- Verify the actor and scope rows are active at provisioning and at every authenticated resolution.

Migration 0013's `human_database_session_binding.role_oid` must identify the dedicated session role, not the actor role. Add `actor_role_oid` or join through `human_session_actor_binding`; do not keep its current FK from session role_oid directly to `human_actor_binding`.

## 4. Provisioning transaction and trusted boundary

A customer-operated control-plane adapter, authenticated independently of API/runtime identities, performs a single transaction:

1. Accept a server-generated unpredictable session UUID, validated actor binding identity, and bounded expiry. Do not accept a role name, tenant, BU, entitlement, or role OID from the browser/API caller.
2. Lock and revalidate the exact active actor and scope binding; derive tenant, BU, issuer, subject and finance entitlements from protected rows.
3. Generate a unique opaque role name server-side, within the existing `pwr_[a-z0-9_]{1,40}` limit. Check both `pg_roles` and `retired_role_identity`; never recycle.
4. Create a NOLOGIN role with NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOINHERIT, NOREPLICATION, NOBYPASSRLS. Verify no role memberships and no unexpected grants.
5. Create the session role's scope binding and immutable session-to-actor binding. Session scope is the actor's existing tenant/BU; all values are database-derived.
6. Grant only the required schema/function privileges for the authenticated scope resolver and required application operations. Do not grant role membership to the provisioner or runtime roles.
7. Ensure the revised database-derived human actor resolver can resolve this session role through the session-to-actor table and returns actor-level entitlements.
8. Change the role to LOGIN as the final transaction step; commit atomically.
9. Return the generated role identity to the broker only after commit. The broker signs a client certificate whose CN exactly matches the unique session role, verifies chain, public key, expiry and role mapping, and only then returns the lease.
10. If certificate issuance or credential-store persistence fails after role creation, invoke idempotent exact-session retirement. The session must not remain login-capable or be reassigned.

The API service must not hold CREATEROLE, superuser, or the session-control role. The trusted provisioner must be separately authenticated and constrained to the specific SECURITY DEFINER provisioning function. Customer DBA review is mandatory for role creation, schema grants, function ownership, certificate authentication mapping and cleanup.

## 5. Broker and issuer changes

Replace `DatabasePrincipal.database_role` as the issued connection identity with an actor identity that has no session login role. The broker should:

- validate OIDC token, MFA/ACR, replay guard and CSR proof-of-possession as today;
- request a new per-session identity from the trusted provisioning adapter using the verified actor key and server-generated UUID;
- receive the exact generated session role name and immutable binding receipt only after the database transaction commits;
- request certificate issuance for that role and the CSR public key;
- verify CN, key, issuer/subject extensions where configured, chain and expiry against the returned binding;
- compensate by retiring the exact session role if certificate issuance/verification fails;
- return session UUID and role only after all checks succeed.

The HumanSessionIssuer must persist credentials with create-only semantics. If storage fails, it must call a trusted exact-session cleanup/revocation adapter; if cleanup cannot be confirmed, surface an incomplete issuance state and alert the customer control plane. Never silently leave an orphaned active session role.

## 6. Connector and database authentication

The connector continues to use TLS verify-full and one physical connection per human session. Its credential provider supplies the unique session role and matching short-lived client certificate. PostgreSQL must authenticate the certificate to that exact role (including the customer's configured `pg_hba.conf` / certificate mapping behavior). The connector must call the registration function with the exact UUID, commit registration, and only then yield the connection.

The registration function compares the database-authenticated `session_user` role OID with the unique session-role OID in the binding. It must not infer identity from `application_name`, GUCs, SQL comments, request headers or caller-provided PIDs.

## 7. Revocation and cleanup lifecycle

For one session UUID:

1. Fence the exact session binding and serialize with admission.
2. Terminate only registered backends whose PID and backend_start still match.
3. Verify no matching backend remains; otherwise return incomplete and permit safe retry.
4. Revoke credential-store retrieval and certificate/lease validity.
5. Set the exact session role NOLOGIN and mark scope/session bindings inactive.
6. Retain immutable role-name/OID retirement records. Do not reuse the role name or OID.
7. Drop the role only after all dependencies/ownership are removed and customer policy permits; this is cleanup, not part of the security proof.

A session revocation must not revoke the actor's base identity or any other session role. Actor-level revocation must fence all sessions derived from that actor, then retire each exact session role.

## 8. Mandatory tests before implementation acceptance

- Two concurrent sessions for one actor produce different role names/OIDs and distinct session UUIDs.
- Session roles map to the same actor, tenant, BU and entitlements, but cannot authenticate as each other.
- A session role cannot resolve another actor or a different tenant/BU.
- Existing actor uniqueness constraints remain intact.
- Session role has no superuser/createdb/createrole/inherit/replication/bypassrls attributes and no unintended memberships.
- A role name already present or retired is rejected; UUID/role/OID reuse is rejected.
- Certificate CN and key must match the provisioned session role and CSR.
- Provisioning, certificate signing, verification and credential-store failure paths retire the exact role or report an explicit incomplete cleanup.
- Session revocation terminates A and preserves B for the same actor.
- Actor revocation fences all associated sessions.
- Registration/revocation races serialize with no unregistered usable connection escaping.
- PostgreSQL 14–17 integration matrix plus Ruff, Mypy, focused pytest and full pytest on exact head SHA.

## 9. Explicit non-claims

This document is not a migration, adapter, role provisioning implementation, certificate mapping implementation, connector integration, or test result. Migration 0013 remains an unaccepted implementation attempt and must not be applied to customer databases or granted revocation execution until its schema and identity assumptions are replaced and reviewed. PS-02.1A and PS-02 remain unaccepted.
