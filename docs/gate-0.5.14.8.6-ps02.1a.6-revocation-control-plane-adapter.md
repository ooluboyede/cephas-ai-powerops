# Gate 0.5.14.8.6 — PS-02.1A.6 PostgreSQL revocation control-plane adapter

Status: source implementation committed; execution and independent review not established.

## Scope

This unit adds `PsycopgSessionBackendRevocationControl` in
`src/powerops/postgres_session_revocation.py`. It implements the existing
`SessionBackendRevocationControl` contract using two separately configured
connection factories:

1. **Fence/provisioner identity:** calls
   `powerops_security.retire_human_session_login(uuid, text)` from migration
   0014. The adapter commits this operation before attempting backend
   termination. The function is idempotent for an already-retired session.
2. **Termination control identity:** calls
   `powerops_security.terminate_human_session_backends(uuid)` from migration
   0015, then calls the new
   `powerops_security.count_human_session_backends(uuid)` verifier. Both
   functions execute as the narrowly privileged `powerops_session_control`
   function owner. The login receives no direct registry-table access or
   `pg_read_all_stats` membership through this adapter.

The adapter accepts only an exact UUID. Backend PID and backend start time are
never supplied by Python; PostgreSQL resolves them from the protected registry.
Termination remains constrained by the migration's PID plus backend_start
match.

## Result validation and retry behavior

- Rejects malformed rows, unexpected result keys, negative counts, booleans
  masquerading as integers, and non-boolean completion values.
- A well-formed incomplete termination result returns its signal count to the
  coordinator. The coordinator independently queries the exact-session
  remaining count and cannot report success unless that count is zero.
- The PostgreSQL termination function records its own secret-free audit events.
  Retries are safe after partial termination because the session remains fenced
  and already-terminated registry rows are not signalled again.
- Connection, SQL, and commit failures are translated to generic
  `SessionRevocationError` messages with exception chaining suppressed.
- Fence and termination factories must be different callable objects and must
  be backed by different customer-configured database identities.

## Customer DBA configuration prerequisite

Do not grant termination authority to the application login, a human session
role, or `powerops_provisioner`. The customer DBA must configure a distinct
termination-control login and explicitly grant it EXECUTE on only:

- `powerops_security.terminate_human_session_backends(uuid)`
- `powerops_security.count_human_session_backends(uuid)`

The fence identity separately needs EXECUTE on
`powerops_security.retire_human_session_login(uuid, text)`. The DBA must
verify the function owners, role attributes, membership graph, schema
permissions, connection authentication, TLS policy, and grants in the
customer's PostgreSQL 14–17 environment before use. The migration's
`powerops_session_control` role remains NOLOGIN and is not itself a
connection credential.

The factories are injected by deployment composition; this unit does not read
DSNs from request data, environment-controlled request fields, or session
claims. Secret storage, rotation, mTLS/TLS configuration, and pool isolation
remain customer deployment responsibilities. The adapter deliberately does
not build or reuse a shared application connection pool.

## Tests added

`tests/test_postgres_session_revocation.py` covers:
- separate factory enforcement and operation routing;
- exact UUID parameter binding;
- commit-before-return for the fence;
- strict termination and count result validation;
- incomplete but valid termination results for coordinator verification;
- commit uncertainty, rollback attempt, connection close, and generic errors;
- use of the protected count function rather than direct registry access.

These are source-level tests only until the repository CI workflow executes them.
The PostgreSQL integration harness and PostgreSQL 14–17 matrix have not been
run as part of this source change. No database migration has been applied to a
customer environment.

## Remaining acceptance requirements

1. Wire the adapter into the customer deployment composition root with two
   distinct credential sources; do not substitute a single shared login.
2. Provide a concrete customer credential-store revocation implementation and
   durable coordinator audit sink. The migration's backend audit table records
   database fencing/termination events, but it is not a substitute for the
   coordinator's actor-attributed application audit.
3. Add integration coverage for fence commit uncertainty, concurrent
   registration/revocation orderings, retry after partial termination, actor
   wide revocation, and exact-session isolation.
4. Execute pytest, Ruff, Mypy, and PostgreSQL 14, 15, 16, and 17 integration
   matrices; inspect actual workflow runs for the resulting head SHA.
5. Obtain independent security review and customer DBA approval.

No customer database was changed. This unit does not certify production
readiness and does not authorize merge or deployment.
