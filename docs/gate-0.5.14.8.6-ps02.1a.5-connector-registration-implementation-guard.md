# PS-02.1A.5 — PostgreSQL Connector Session Registration: Implementation Guard

Status: design/implementation guard only. No connector registration code or backend-registry migration is accepted by this document.

## Repository baseline inspected

Branch: `security/revenue-assurance-gate-0.1`
Prior implementation head: `0e69192cfa4fe401137dcbdc32afcb5e96ccada8`

Inspected:
- `src/powerops/postgres_certificate_connector.py`
- `src/powerops/human_sessions.py`
- `src/powerops/human_session_issuer.py`
- `migrations/postgresql/0013_exact_human_session_backend_registry.sql`
- `migrations/postgresql/0014_per_session_human_login_identity.sql`
- `tests/test_postgres_certificate_connector.py`

## Confirmed current behavior

1. `PsycopgHumanSessionConnector` opens a new physical connection using the trusted credential provider's per-session role and client certificate.
2. TLS uses `sslmode=verify-full`, customer root certificate, client certificate and private key. The role is not caller-selectable.
3. The connector currently yields the connection without registering its PostgreSQL backend.
4. `HumanDatabaseSession.connection()` starts its application transaction only after the connector yields. Registration therefore belongs in the connector's pre-yield phase and must commit before any application SQL is possible.
5. Migration `0014` establishes `powerops_security.human_session_actor_binding`, whose `session_role_oid` is distinct from `actor_role_oid`.

## Why migration 0013 is not reusable

Migration `0013` predates the per-session login model:
- `human_database_session_binding.role_oid` references `human_actor_binding(cluster_id, role_oid)`, so it cannot represent the new dedicated session role as written.
- Its provisioning function searches the actor binding by the session role OID.
- Its backend registration function likewise compares the authenticated session role OID to an actor role OID.
- It has no correct join through `human_session_actor_binding`.
- It was intentionally removed from automatic CI application and must remain unapplied pending replacement.

Do not edit or apply migration 0013 as a shortcut. Do not grant its functions or broad backend privileges to application roles.

## Required design for the corrected registry

The next migration must add a protected backend registry tied to migration 0014:

- Session binding key: exact `session_id` FK to `human_session_actor_binding`.
- Backend identity: PostgreSQL-derived `pg_backend_pid()` plus `pg_stat_activity.backend_start`; never accept PID, backend_start, tenant, BU, role OID, or actor identity from the caller.
- Registration: a SECURITY DEFINER function called on the actual per-session connection. It must derive `session_user`'s role OID, lock the exact active session binding `FOR SHARE`, verify the binding's session role OID/name and expiry, verify the associated actor is still active, then insert the exact PID + backend_start tuple.
- Revocation: a separate customer-approved control-plane function must lock the same exact session row `FOR UPDATE` and deactivate/fence it before enumerating registered backends. This row-lock ordering serializes registration against revocation: registration that wins is recorded before revocation proceeds; revocation that wins causes later registration to fail.
- Termination: signal only a registry entry whose PID and backend_start still match `pg_stat_activity`. Never signal a PID based on a caller argument or PID alone. Recheck remaining matching backends and report incomplete if any remain.
- Transaction behavior: connector invokes registration on the new connection, validates exactly one affirmative result, commits registration before yielding the connection, and closes/rolls back on any error. The first application query must occur only after registration commit.
- Least privilege: session roles receive only the narrowly scoped registration capability. Revocation and backend-signal authority remain in a separately controlled NOLOGIN/customer-approved control plane. No broad PUBLIC grant.
- Audit: durable, secret-free records for registration, fencing, termination attempts and incomplete outcomes; no private key, token, certificate PEM, or credential material.
- Retry: exact-session revocation must be idempotent; uncertain outcomes must be safely retryable without reactivating a session or signalling a reused PID.

## Required Python connector behavior

1. Verify that credential session UUID, role, principal, certificate CN, and expiry form one binding.
2. Open a fresh TLS verify-full connection as the session role.
3. Call the registration function using only the exact session UUID from the trusted credential object.
4. Require one database-confirmed success result.
5. Commit the registration transaction before yielding.
6. On missing function, false result, malformed result, SQL error, commit uncertainty, or connection failure: do not yield; close the connection; return a generic fail-closed session error. Credential/role retirement compensation must be coordinated without claiming that an uncertain commit was rolled back.
7. Keep the existing identity/entitlement check in `HumanDatabaseSession`; registration is an additional admission check, not a replacement.

## Required tests before this gate can be accepted

Unit tests:
- Registration happens before yield and before application SQL.
- Correct exact session UUID is passed; no caller-supplied PID or role is accepted.
- False, empty, malformed and exception results fail closed.
- Registration commit happens before yield.
- Failure closes the connection and never yields.
- Commit-uncertain outcome is not reported as clean rollback.
- A second connection for the same session registers as a distinct backend.

PostgreSQL integration tests on versions 14, 15, 16 and 17:
- Two simultaneous per-session roles for the same actor.
- Multiple physical backends registered to one session.
- Exact registration/revocation race in both lock orderings.
- Revocation prevents all later registrations for that session.
- Backend termination requires PID AND backend_start match.
- PID reuse/stale registry row cannot terminate a different backend.
- Termination and remaining-backend counts are verified.
- Actor-wide revocation fences every session and terminates registered backends through the approved control plane.
- Runtime roles cannot read or mutate protected registry tables or invoke revocation.
- Failure, timeout and retry paths preserve fail-closed behavior.

## Acceptance boundary

This inspection found the integration gap and the migration incompatibility. It did not implement registration, create a replacement migration, run tests, apply SQL, or demonstrate backend termination. PS-02.1A.5 remains unaccepted until the corrected migration, connector integration, tests, and independent review are complete.
