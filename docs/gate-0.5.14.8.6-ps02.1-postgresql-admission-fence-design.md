# PS-02.1 — PostgreSQL admission fence and exact backend registry

Status: design only. Migration 0013 is present in the branch but is not accepted as safe for runtime use. No PostgreSQL adapter or runtime revocation behavior is accepted by this document.

## 1. Source inspection findings

The current human-session connector opens a fresh TLS connection using a broker-assigned database role, but it does not register the session UUID with PostgreSQL. Its `application_name` is a constant and cannot identify an exact human session.

Migrations 0010–0012 bind a database role to a human actor and business-unit scope. They do not bind a unique session UUID to a unique PostgreSQL login role. In particular, migration 0010 has both a primary key on (cluster_id, role_oid) and a unique constraint on (cluster_id, issuer, subject, tenant_id, business_unit_id). The broker's `DatabaseSessionBroker.issue_session` obtains the database role from the existing identity directory and then generates a new UUID; it does not provision a new role for that UUID. Consequently, two concurrent application sessions for the same actor can share one PostgreSQL `session_user`.

### 1.1 Blocking identity-model mismatch — PS-02.1A

Migration 0013 resolves the PostgreSQL `session_user` to a role OID and uses that role OID to select a session binding. If multiple session UUIDs share the same login role, the database cannot determine which UUID belongs to the current backend. A client-supplied UUID does not prove the mapping. The current function's role-OID comparison therefore does not establish one-to-one session identity.

This is a correctness and security blocker: a backend could be registered against an incorrect session UUID, and revocation could terminate the wrong session's backend set. Do not integrate migration 0013 with the connector, grant its revocation function, or claim exact-session termination until PS-02.1A is resolved.

## 2. Required identity-model change

The database must establish a one-to-one relationship between each issued session UUID and a dedicated, non-reused PostgreSQL LOGIN role (or another cryptographically authenticated per-session database identity that PostgreSQL itself exposes to the registration function).

For the dedicated-role design, all of the following are mandatory:

- A single human actor may have multiple concurrent session roles; the existing actor/scope uniqueness constraint must not be weakened in a way that permits ambiguous actor resolution.
- Each session role has exactly one immutable session UUID binding and cannot be reassigned to another session or actor.
- Role creation, certificate issuance, session-binding creation, expiry, and cleanup are coordinated by a trusted customer control plane. The API runtime cannot create roles or choose role names.
- The certificate common name and PostgreSQL authenticated login role must identify that exact session role; the broker must verify this binding before returning the lease.
- The session UUID binding must also point to the existing human actor/scope identity and inherit its tenant, BU, and finance entitlements from database-owned records.
- Revocation first fences the exact session binding, terminates only backends registered under that unique login identity, verifies none remain, and then retires the login role with NOLOGIN. Role names/OIDs must never be reused for another session.
- Role creation, grant/revoke privileges, role membership, certificate mapping, cleanup, failure recovery, and concurrent issuance/revocation require explicit least-privilege design and customer DBA approval.

An alternative to one-role-per-session is acceptable only if it provides an equally strong database-authenticated, non-spoofable per-connection session identity. Caller-provided UUIDs, GUCs, application_name, SQL comments, request headers, or API-supplied PIDs are not such an identity.

## 3. Required session binding and backend registry

Only after PS-02.1A has a reviewed identity model should an additive migration implement the protected registry in `powerops_security`.

A session binding must include the unpredictable session UUID, cluster, unique authenticated session role identity, existing actor/scope binding, expiry, and active/revoked state. The backend registry must record exact session UUID, PID, backend start timestamp, and registration timestamp. PID and backend start must both match to avoid PID reuse.

Provisioning must create the role and immutable binding through a trusted customer control plane before the lease is returned. Runtime and human roles must not write registry tables directly.

## 4. Admission and revocation protocol

The connector must register immediately after TLS connection establishment and before yielding the connection. Registration derives the authenticated database identity, PID, and backend start from PostgreSQL itself, locks the exact active binding, verifies the database-authenticated identity is uniquely bound to the session UUID, inserts the backend registry row, and commits before yielding. Any failure closes the connection.

Revocation accepts one session UUID, fences its exact binding using a lock that serializes with admission, joins registry rows to `pg_stat_activity` by PID and backend start, terminates only those exact backends, and verifies that none remain. Use bounded lock and statement timeouts. Partial failures remain incomplete and retryable. A dedicated NOLOGIN control role may hold only the privileges approved by the customer's DBA; do not grant superuser to runtime roles or the general provisioner.

## 5. Required integration tests

After the identity model and migration are corrected, run against PostgreSQL 14–17:

1. Two simultaneous sessions for the same actor receive distinct database-authenticated session identities.
2. Each backend can register only under its own session UUID.
3. Revoking session A terminates A and preserves session B for the same actor and BU.
4. Unknown, expired, revoked, or mismatched session identities fail closed.
5. Registration-first/revocation-first races serialize with no unregistered usable connection escaping.
6. PID reuse and stale registry rows cannot target a different backend.
7. Insufficient privilege, lock/statement timeout, database outage, and termination failure fail closed.
8. Retry converges without affecting unrelated sessions.
9. Audit events contain no credentials, private keys, tokens, or caller-supplied backend identifiers.

Mock-only tests are insufficient.

## 6. Migration 0013 disposition

The current `migrations/postgresql/0013_exact_human_session_backend_registry.sql` is an implementation attempt, not an accepted security control. It looks up a pre-existing actor role and uses that role OID as the session discriminator, while the broker can issue multiple UUIDs against that same role. The migration must not be treated as production-safe, and its CI wiring must not be interpreted as proof of correctness. Correct or replace it only after the one-to-one identity model is designed and reviewed. Do not apply it to a customer database or grant execution on its revocation function.

## 7. Acceptance evidence

PS-02.1A/PS-02.1 remain unaccepted until there is a reviewed per-session database identity model, broker/provisioner integration, a corrected additive migration, connector registration and concrete revocation adapter, PostgreSQL 14–17 race/isolation tests with retained CI logs, static and full test results on the exact head SHA, and independent security retest.

## 8. Explicit non-claims

This document does not implement or validate per-session role provisioning, a PostgreSQL adapter, backend registration, termination, revocation SLA, production certification, deployment approval, or permission to merge PR #21.
