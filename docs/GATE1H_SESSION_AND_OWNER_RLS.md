# Gate 1H — active-session fencing and forced-RLS owner-path validation

**Status: implementation submitted; execution evidence pending. Gate 1H is NOT PASSED.**

Gate 1H runs against a disposable PostgreSQL service only. It starts from the Gate 1F fixture to isolate the new assertions. Gate 1G remains a separate unresolved validation gate; this branch does not claim to repair or pass Gate 1G.

## Added assertions

1. Provision a dedicated disposable tenant login and hold a real PostgreSQL backend open.
2. Retire the login. Confirm PostgreSQL `NOLOGIN` does not terminate the already-authenticated backend.
3. Confirm the still-open backend can no longer resolve an active scope because the binding is inactive and the tombstone exists.
4. Explicitly terminate the backend with `pg_terminate_backend`, confirm it disappears from `pg_stat_activity`, and confirm a new connection is rejected.
5. Exercise a `SECURITY DEFINER` function owned by a non-login, non-superuser table-owner role against a table with both `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`. The authenticated caller is a BU-scoped login; the expected visible row count is one.

## Run

```bash
bash tests/postgresql/run_gate1h.sh
```

## Important boundaries

- This validates explicit session termination, not a production connection-pool implementation. Application pool eviction, transaction-pooler behavior, credential rotation, and reconnect races require integration tests against the selected pooler and application runtime.
- The owner-path probe tests a non-login table owner through a `SECURITY DEFINER` function. It does not claim that PostgreSQL superusers or roles with `BYPASSRLS` are constrained by RLS; those remain privileged trust boundaries.
- It does not validate clone/restore fencing, partition routing, materialized views, triggers, background workers, future-table default privileges, or foreign-key side channels.
- Gate 1G's current workflow is failing and its job logs could not be retrieved through the available GitHub log endpoint. Gate 1H does not mask that failure.
- No customer data, IBEDC environment, SCADA/ADMS/DMS integration, or control path is used.

## Acceptance

Do not accept Gate 1H until exact-head CI passes on PostgreSQL 14–17, SQLSTATEs and job output are reviewed, and an independent PostgreSQL security reviewer signs off. Passing this gate alone is not production certification.
