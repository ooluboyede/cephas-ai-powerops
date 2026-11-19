# PS-02.1 — PostgreSQL admission fence and exact-backend registry design

**Status:** Design decision only — implementation and acceptance pending  
**Parent:** Gate 0.5.14.8.6 / PS-02  
**Supported baseline:** PostgreSQL 14–17  
**Scope:** Exact human database-session admission, revocation and backend termination

## 1. Current-state finding

The current `PsycopgHumanSessionConnector` opens one physical TLS connection for a human operation and uses the broker-assigned database role. It sets a constant `application_name`; it does not register the exact session UUID or backend identity with PostgreSQL.

The Python `SessionBackendRevocationControl` is only a protocol. There is no concrete PostgreSQL control adapter, admission fence, backend registry, migration, or PostgreSQL integration test for this path. Mock tests cannot establish backend termination.

**Do not treat `application_name`, a caller-provided PID, a client-set GUC, or a tenant/role-wide termination query as proof of session identity.** `application_name` and client-set GUCs are not trusted security bindings.

## 2. Required database-owned model

The customer PostgreSQL deployment must provide a control schema containing:

- An immutable mapping from the broker-issued, per-session database login role to the exact application session UUID and credential expiry.
- One revocation state row per exact session UUID. The state is monotonic: active → revoked; no un-revoke operation.
- A backend registry keyed by exact session UUID and the backend identity tuple: PID, `backend_start`, and authenticated `session_user`/role identity.
- Security-definer admission and revocation functions owned by a non-login customer control owner. Runtime session roles receive only the minimum EXECUTE privileges required; they receive no direct write access to control tables.
- A dedicated, separately authenticated revocation control identity. It must not be the application runtime login.

The registry must bind a connection to the session by deriving the session UUID from the trusted database-login-role mapping for `session_user`. The admission function must not accept a session UUID or PID from the client as authority.

## 3. Admission/revocation serialization

The database functions must serialize admission and revocation on the same exact-session state row:

1. On connection admission, a security-definer function resolves `session_user` to its provisioned session UUID and locks that session's state row.
2. It rejects missing, expired, or revoked sessions.
3. While holding the row lock, it records the current backend identity using database-derived values, including PID and `backend_start`, then commits.
4. Revocation locks that same state row, marks it revoked, and commits the fence before attempting termination.
5. Because both operations lock the same row, an admission that began first must finish registering before revocation can fence; an admission that arrives after the fence observes revoked and is rejected.
6. The revoker reads only registry entries for the exact UUID. Before termination it verifies the current activity still matches the recorded PID, `backend_start`, and authenticated role, preventing PID reuse from targeting an unrelated backend.
7. It terminates only those exact non-superuser backends, then independently verifies that no matching registered backend remains active. Stale registry rows may be cleaned only after the corresponding backend is confirmed absent.

A transaction-level row lock is the serialization primitive; no hash-based advisory-lock identity is required. The admission registration and revocation state transition must be transactionally atomic.

## 4. Privilege and data-access boundary

- Human session roles must be non-superuser and must not inherit privileged roles.
- The control owner must be NOLOGIN and unavailable to runtime credentials.
- The revocation identity must have only the customer-approved authority needed to execute the control function and signal eligible session backends. PostgreSQL version-specific privilege behavior must be tested on 14, 15, 16 and 17.
- The control function must not terminate superuser sessions. It must fail closed if the exact backend cannot be safely identified or signalled.
- Protected human-session data access must be denied unless the current backend has a live registry entry for the authenticated `session_user` and an active session state. Merely calling an admission function must not grant broader table privileges.
- Customer administrators must decide whether access is mediated by security-definer data functions or by RLS policies that validate the database-owned backend registry. Direct table grants must not bypass the active-session check.
- Connection setup must invoke admission before any protected query. If admission fails, the connection is closed and no business operation runs.

## 5. Required adapter behavior

The concrete Python adapter must use a dedicated control connection and bounded connection, lock, and statement timeouts. It must implement:

- `fence_session(session_id)`: idempotently persist the exact-session revoked state.
- `terminate_session_backends(session_id)`: discover backend identities from the database-owned registry only, terminate only exact matching backends, and return a validated count.
- `active_session_backend_count(session_id)`: independently query live PostgreSQL activity for that exact session and return a non-negative integer.
- Safe retries after partial completion. A retry must not reopen admission or affect another session.

No caller-supplied PID, database role, tenant, or business-unit value may widen the target set.

## 6. Mandatory integration tests

Run against real PostgreSQL 14, 15, 16 and 17 instances:

1. Two concurrent sessions for distinct UUIDs; revoking one leaves the other connected and able to perform its permitted operation.
2. Admission wins the state-row lock first; revocation waits, fences, then terminates the newly registered backend.
3. Revocation wins first; a concurrent and subsequent admission for that UUID is rejected before protected access.
4. Multiple physical connections mapped to one session UUID are all terminated.
5. PID reuse / stale registry row cannot terminate a different backend.
6. Spoofed `application_name`, client GUCs, UUIDs and PIDs cannot register or target another session.
7. Runtime login cannot read or mutate registry/state tables, assume control-owner privileges, or execute revocation.
8. Revoker with insufficient privilege, database outage, lock timeout, statement timeout, and partial termination all fail closed and remain safely retryable.
9. Backend disappearance is independently verified; a nonzero remaining count never reports success.
10. Revocation latency is measured under concurrent connection churn and documented against an agreed customer SLA.

## 7. Acceptance gate

PS-02.1 is not accepted until the customer-specific migration/functions, privilege audit, connector admission hook, concrete Python control adapter, and real PostgreSQL 14–17 concurrency/security tests exist and pass. Ruff, Mypy, full Python tests, and independent security retest are also required.

This document is a design constraint, not an implemented database control, not evidence of termination, and not production certification. No customer database, CA, or privilege model has been selected or configured.
