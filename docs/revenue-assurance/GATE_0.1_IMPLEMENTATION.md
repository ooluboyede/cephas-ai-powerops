# Gate 0.1 — Backend and application foundation

## Implemented in this branch

- FastAPI Revenue Assurance route layer and typed request/response contracts.
- Trusted-principal boundary: API does not accept tenant or business-unit identity from caller-controlled headers, query parameters or payloads.
- Role checks for investigation creation, reviewer decisions, approval and verified recovery outcomes.
- Repository port that requires server-derived scope on every operation.
- Fail-closed behavior: absent authenticated principal is 401; absent persistence adapter is 503.
- Additive PostgreSQL migration 0006 for source batches, findings, investigation cases, decisions, recovery outcomes and append-only audit events.
- Forced RLS policies use the existing powerops_security.row_scope_permits(tenant_id,business_unit_id) predicate.
- Composite foreign keys prevent a case, decision or recovery row from referencing a parent in another tenant or business unit.
- Explicit post-migration grant function provisions the new schema only to an active, non-superuser, business-unit-scoped login; tenant-wide logins are rejected.
- Runtime grants are least-privilege: SELECT/INSERT on domain tables and UPDATE only on investigation case status; source findings and source batches cannot be rewritten by the runtime login.
- Disposable PostgreSQL integration harness verifies BU reads, tenant-wide grant rejection, cross-BU insert denial, source-evidence write restrictions and audit immutability.
- API contract and automated route tests.

## Existing work preserved

This branch starts from security/0.1.1-gate1i-credential-rotation-eviction and carries forward the existing 0.1.0 application bootstrap, migrations 0001–0005, PostgreSQL security gates 1E–1I, and PR #20 Revenue Assurance PoV/dashboard and product/commercial documents.

## Explicit limitations

- OIDC/JWT verification and identity-provider integration are not implemented. The app accepts a principal only when trusted middleware has populated request state; absent middleware returns 401.
- A concrete PostgreSQL repository adapter is implemented. Configure DATABASE_URL with a dedicated BU-scoped login and install requirements-postgres.txt. The adapter verifies the authenticated database scope on each operation and opens a fresh connection per operation. A managed connection pool and secret-manager rotation lifecycle remain unimplemented.
- PostgreSQL migration, repository and RLS checks must execute successfully on supported PostgreSQL versions before the schema gate can be marked passed.
- No live utility integrations, customer data, model inference, automatic billing action, recovery execution, disconnection or grid-control command is implemented.
- CI success and PostgreSQL security gate success are separate evidence. Do not infer one from the other.

Gate 0.1 is an engineering foundation, not a production release or certification.
