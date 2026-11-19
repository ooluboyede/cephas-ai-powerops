# PS-02.1 — PostgreSQL admission fence and exact backend registry

Status: implementation design; no PostgreSQL adapter, migration, or runtime behavior is added by this document.

## 1. Source inspection findings

The current human-session connector opens a fresh TLS connection using a broker-assigned database role, but it does not register the session UUID with PostgreSQL. Its `application_name` is a constant and therefore cannot identify an exact human session.

The current database identity model in migrations 0010–0012 binds a database role to a human actor and business-unit scope. It does not bind a unique session UUID to a backend. The human actor uniqueness constraint is actor/scope based, so assuming that each actor already has a unique database role per session would be incorrect.

The Python `SessionBackendRevocationControl` remains a protocol. There is no concrete PostgreSQL control adapter. The mock tests do not demonstrate backend termination or connect/revoke race safety.

## 2. Required database model

Implement this only as an additive migration after the current human-actor migrations. Keep the session registry in the protected `powerops_security` schema.

### 2.1 Exact session binding

A protected `human_database_session_binding` row must bind:
- one unpredictable session UUID;
- the cluster identity;
- the database role OID resolved from PostgreSQL catalogs (not a caller-supplied OID);
- the corresponding active human actor binding;
- the certificate/session expiry;
- active/revoked state and immutable revocation metadata.

The primary key is the exact session UUID. Enforce one active binding per session and reject reuse of a UUID for a different role, actor, tenant, BU, or expiry. The provisioning function must be executable only by the trusted database provisioner/control plane. The API runtime and human database roles must not insert, update, or delete these rows.

A provisioning adapter must create this binding before the lease is returned to the API caller. Until that broker-to-database provisioning handshake exists, the session UUID cannot be considered database-authenticated.

### 2.2 Backend registry

A protected `human_database_session_backend` table records:
- exact session UUID;
- backend PID;
- backend start timestamp;
- registration timestamp.

Use (session UUID, PID, backend start timestamp) as the identity key. PID alone is reusable and is not a safe durable identifier. The table is not writable by application SQL or human roles.

### 2.3 Admission registration function

A narrowly scoped SECURITY DEFINER function must:
1. derive the actual login identity from `session_user` and resolve its role OID from `pg_roles`;
2. lock the exact active session-binding row using a lock mode that conflicts with the revoker's state-changing UPDATE;
3. verify the binding role OID equals the actual login role OID;
4. verify the session and certificate expiry;
5. obtain PID and backend start time from PostgreSQL itself;
6. insert the backend registry row;
7. return only a non-secret success marker.

The function must not accept a PID, role name, tenant ID, BU ID, or actor subject from the caller. It must use a fixed safe search_path, have PUBLIC execution revoked, and be executable only by the human session roles that are provisioned for this feature.

The connector must call this function immediately after TLS connection establishment and before yielding the connection to application code. It must commit the registration transaction before yielding. Any registration error closes the connection and fails closed. A caller-supplied `application_name` is telemetry only, never security authority.

## 3. Revocation and race protocol

The trusted revocation function accepts one session UUID and executes in one bounded transaction:

1. Lock and atomically mark that exact session binding inactive. This UPDATE must conflict with the admission function's row lock.
2. Because both operations serialize on the same binding row, an admission that wins the lock first commits its registry row before revocation proceeds; an admission that arrives after revocation sees inactive state and is rejected.
3. Resolve candidate backends by joining the exact session's registry rows to `pg_stat_activity` on both PID and backend start time.
4. Call `pg_terminate_backend` only for those resolved exact backend identities. Never accept PIDs from the API, and never terminate by role, tenant, or BU alone.
5. Re-check `pg_stat_activity` for the same exact identities. Return verified success only when none remain.
6. Record immutable, secret-free audit metadata for the actor, exact session UUID, counts, and outcome.

The controller's privilege to terminate backends must be explicit and least-privileged (for example, a dedicated NOLOGIN control role with only the required PostgreSQL signal privilege, subject to customer DBA approval). Do not grant superuser to the API runtime, human login, or general provisioner merely to make this work.

Use bounded `lock_timeout` and `statement_timeout`. If the admission lock cannot be acquired, the registry is inconsistent, the termination privilege is insufficient, the database is unavailable, or a backend remains, return an incomplete/error outcome. Retrying must converge safely. Do not turn a timeout into success.

## 4. Required connector changes

- Replace the constant-only connection setup with an immediate call to the database registration function using the exact lease session UUID.
- Ensure registration completes and commits before the connection is yielded.
- Close the physical connection if registration fails.
- Keep TLS verify-full, broker-supplied role, exact credential checks, short certificate TTL, and one-connection-per-human-operation behavior.
- Do not treat `application_name`, client GUCs, SQL comments, request headers, or a caller-selected PID as trusted identity.

## 5. Required integration tests

Run against each supported PostgreSQL major version (14–17):

1. A registered session is visible under its exact UUID and backend start time.
2. Revoking session A terminates A's backend and preserves session B, even where both sessions belong to the same human actor or business unit.
3. A client cannot register a session UUID bound to another role.
4. A client cannot register an unknown, expired, or revoked UUID.
5. Concurrent registration/revocation: registration-first is visible and terminated; revocation-first makes registration fail; no usable unregistered connection escapes the connector.
6. PID reuse/stale registry rows do not target a different backend because backend start time must also match.
7. Insufficient signal privilege, lock timeout, statement timeout, database outage, and termination failure all fail closed.
8. Partial failure followed by retry reaches verified completion without affecting unrelated sessions.
9. The audit record contains no credentials, private keys, tokens, or caller-supplied backend identifiers.

The test harness must create two simultaneous exact sessions and use separate physical connections. Mock-only tests are insufficient.

## 6. Acceptance evidence

PS-02.1 is not accepted until all of the following exist:
- additive migration and privilege review;
- trusted broker/provisioner integration that creates the exact session binding before lease issuance;
- connector registration and concrete PostgreSQL revocation adapter;
- PostgreSQL 14–17 race and isolation tests with retained CI logs;
- Ruff, Mypy, focused pytest, and full pytest results on the exact head SHA;
- independent security retest of the exact resulting commit.

## 7. Explicit non-claims

This document does not implement a PostgreSQL adapter, migration, database privilege grant, broker integration, backend registration, termination, or revocation SLA. It does not establish PS-02 acceptance, production certification, deployment approval, or permission to merge PR #21.
