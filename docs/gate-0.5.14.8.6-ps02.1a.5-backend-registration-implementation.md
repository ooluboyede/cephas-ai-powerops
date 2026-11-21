# PS-02.1A.5 — Per-session PostgreSQL backend registration implementation

Status: source implementation committed; validation and independent acceptance pending.

## Scope delivered

- Added `migrations/postgresql/0015_human_session_backend_registry.sql`.
- Updated `PsycopgHumanSessionConnector` to register the actual backend before yielding a connection.
- Added connector unit tests for successful registration, malformed/false results, rollback and uncertain commit failure.
- Added PostgreSQL integration harness `tests/postgresql/run_gate0_5_14_8_6_ps021a5.sh`, invoked from the existing PS-02.1A.3 harness before actor-wide revocation.
- Added the migration/harness to the existing PostgreSQL 14–17 CI path through the existing workflow step.

## Migration 0015

Requires migration 0014 and intentionally does not apply or depend on migration 0013.

- Creates protected `human_session_backend_registry`, keyed by exact session UUID, backend PID and backend_start.
- Creates durable secret-free backend audit records.
- Creates a SECURITY DEFINER registration function. The function derives session_user role OID, backend PID and backend_start from PostgreSQL; caller supplies only exact session UUID.
- Locks the matching active `human_session_actor_binding` row FOR SHARE and revalidates current actor and scope entitlement. The lock is held through the caller's registration transaction.
- A trigger grants the narrowly scoped registration function to each new session login during provisioning. A backfill grants it to still-active sessions created before migration 0015.
- Creates a separate control-plane termination function. It refuses active sessions; the caller must first commit exact-session retirement through migration 0014's `retire_human_session_login`, which locks and fences the same binding row.
- Termination signals only registry rows whose PID AND backend_start both match `pg_stat_activity`; it reports completion only after no matching registered backend remains.
- The control function owner is NOLOGIN and receives `pg_signal_backend` and `pg_read_all_stats`. A customer DBA must approve this privilege model and explicitly grant EXECUTE on the termination function to a separately authenticated control plane. No application/session role receives termination authority.

## Connector behavior

The connector now calls:

`SELECT powerops_security.register_human_session_backend(%s) AS registered`

inside a dedicated transaction, using only the trusted credential object's session UUID. It requires a dict result with `registered is True`, commits the registration transaction, and only then yields the connection. Any missing/false/malformed result or transaction/commit exception prevents yielding; the connection context closes and the public error remains generic.

The existing identity/entitlement verification in `HumanDatabaseSession` remains in place.

## Tests added, not yet executed

Unit coverage added:
- Registration is called with exact session UUID.
- Registration commits before yield.
- Missing, false and malformed result fails closed and rolls back.
- Uncertain commit exception closes the connection and does not yield.

PostgreSQL harness coverage added:
- Two physical backends registered to one session.
- Exact retirement fences the session before backend termination.
- PID plus backend_start matching is used.
- Stale registry entry with a mismatched backend_start is not signalled.
- Audit records are present.

The harness is wired to the PostgreSQL 14–17 matrix, but no run result is available at this commit. No SQL migration execution, pytest, Ruff, Mypy, or PostgreSQL matrix pass is claimed.

## Remaining gaps / review requirements

- The current harness does not yet exercise both possible concurrent registration-vs-revocation lock orderings deterministically, nor PID reuse under an actual reused PID. Those remain required before acceptance.
- The Python revocation coordinator still needs a concrete customer control-plane adapter that performs committed exact-session retirement followed by `terminate_human_session_backends`, validates the result and retries incomplete termination.
- Migration 0015's use of PostgreSQL predefined roles must be reviewed and approved by each customer DBA. A separate control-plane EXECUTE grant is deliberately not supplied by the migration.
- Validate SQL on PostgreSQL 14, 15, 16 and 17; run focused tests, full pytest, Ruff and Mypy; then obtain independent review.
- Migration 0013 remains an incompatible, unaccepted attempt and must not be applied.

## Acceptance boundary

This is source implementation, not a validated or accepted security gate. No customer database was modified, no production deployment or certification is implied, and PR #21 remains open/draft/unmerged.
