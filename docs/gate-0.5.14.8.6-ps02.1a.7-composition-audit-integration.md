# Gate 0.5.14.8.6 — PS-02.1A.7 production composition and audit integration

Status: source implementation committed; CI and PostgreSQL execution not yet established.

## Implemented

### Explicit composition boundary

`src/powerops/session_revocation_composition.py` adds
`build_human_session_revocation_coordinator(...)`. It composes:

- the existing customer-supplied encrypted `HumanSessionCredentialStore`;
- the 0014 provisioner identity used to fence one exact session;
- the 0015 termination-control identity used to terminate and verify exact
  registered PostgreSQL backends;
- the 0016 audit-writer identity used only to append the coordinator's
  actor-attributed audit record.

The builder rejects reused connection-factory objects. This is a configuration
guard, not proof that three different factories resolve to three different
database principals. The customer must verify actual database identities,
secret sources, TLS, pool separation and grants.

### Append-only coordinator audit

Migration
`migrations/postgresql/0016_human_session_revocation_audit.sql` creates
`powerops_security.human_session_revocation_audit` and a narrow
SECURITY DEFINER append function,
`record_human_session_revocation_audit(...)`.

- The table stores only event type, actor subject, exact session UUID, outcome,
  backend count and three containment booleans, plus database writer identity
  and timestamp. It stores no token, certificate, private key, DSN or backend
  connection detail.
- The function validates bounded actor subject, exact UUID, allowed event and
  outcome values, nonnegative counts and consistency of a verified outcome.
- The audit table is owned by NOLOGIN `powerops_revocation_auditor`.
  The writer login receives EXECUTE on the append function only; it must not
  receive direct table INSERT, UPDATE or DELETE.
- The migration does not grant the writer login automatically. A customer DBA
  must create/configure a dedicated login and grant USAGE on the security
  schema plus EXECUTE on the function.

`src/powerops/postgres_session_revocation_audit.py` implements the existing
`SessionRevocationAudit` contract. It validates payloads before connecting,
uses parameterized SQL, requires a returned audit ID and acknowledged commit,
and emits generic errors without exception-chain disclosure.

### CI and tests

Added:
- `tests/test_postgres_session_revocation_audit.py`
- `tests/postgresql/run_gate0_5_14_8_6_ps021a7.sh`
- CI focused Python tests and a PostgreSQL audit migration step after the
  existing PS-02.1A.3/1A.5 harness.

The integration script applies migration 0016, creates a disposable writer
login, verifies EXECUTE is granted while direct table DML is absent, writes a
verified audit event through the SECURITY DEFINER function, and checks that
exactly one row is persisted.

## Explicitly not implemented / not claimed

- No concrete HashiCorp Vault, cloud secret manager, or customer credential
  store implementation is selected or wired. The composition deliberately
  requires the customer's existing `HumanSessionCredentialStore` injection.
  Its production adapter, revocation semantics, and vault audit/TTL controls
  must be reviewed separately.
- No HTTP endpoint or API route is exposed by this unit. The caller must invoke
  the coordinator only after normal OIDC authentication and authorization.
- Factory object inequality does not establish distinct credentials. Customer
  deployment must prove separate PostgreSQL login identities and isolated
  secret/pool configuration.
- The integration harness uses disposable local CI roles and credentials; it
  is not evidence of customer DBA approval or production secret management.
- No test, Ruff, Mypy, PostgreSQL 14–17 matrix or workflow result is claimed
  until a run for the resulting head SHA is inspected.
- No customer database was modified.

## Acceptance sequence

1. Run all Python quality checks and the complete test suite.
2. Execute migrations 0014, 0015 and 0016 and all PostgreSQL harnesses on
   PostgreSQL 14, 15, 16 and 17.
3. Inspect exact job logs and artifacts for the current commit SHA.
4. Add a concrete customer credential-store adapter and deployment configuration
   with verified independent DB identities.
5. Independently review migration ownership/grants, role membership, function
   execution rights, audit immutability, uncertain commit behavior, revocation
   races and credential-store revocation.
6. Reassess PS-02.1A.6/1A.7 together before gate acceptance.

No merge, deployment or production certification is authorized by this unit.
