# PowerOps 0.1.1 — Identity, Tenant Context and PostgreSQL RLS Design Gate

Status: **DESIGN PROPOSAL — NOT IMPLEMENTED**
Baseline: `258d6f963aa7cca518800d196c40f3f6fdf22943`
Target release: `0.1.1`
Working branch: `feat/0.1.1-identity-tenant-rls`

## 1. Objective and release boundary

Introduce a provider-neutral identity boundary, server-verified tenant and business-unit (BU) context, and PostgreSQL-enforced row isolation. The application must fail closed whenever identity, membership, tenant context, BU context, or database transaction context is absent or invalid.

This milestone is not production certification. It does not add live utility integrations, operational control, SCADA/DMS write paths, or authorisation to operate a distribution network.

## 2. Identity integration contract

1. Use OpenID Connect (OIDC) bearer access tokens. The identity provider is selected per customer deployment; no provider is assumed by this design.
2. Configure the exact issuer and audience per deployment. Never accept an issuer or audience supplied by a request.
3. Validate signature using the configured issuer's trusted JWKS; allow-list asymmetric algorithms only (initial implementation target: RS256). Reject `none`, symmetric algorithms, unknown key IDs, invalid signatures, expired tokens, not-yet-valid tokens, issuer mismatch, and audience mismatch.
4. Require a stable subject claim. The subject is namespaced by issuer; do not treat email or display name as a principal identifier.
5. Map tenant and BU access to verified server-side membership records. Token claims may identify the user, but client-supplied tenant/BU values are never authoritative. Any requested active BU must be checked against the authenticated principal's current membership.
6. Do not implement a local password store or custom authentication protocol in this milestone.
7. Missing identity configuration must prevent protected routes from starting in a deployment that enables authentication; there must be no silent development bypass in production mode.

## 3. Principal and request-context contract

The authenticated principal contains:
- issuer and subject;
- resolved internal principal ID;
- active tenant ID;
- active BU ID;
- verified role/permission set;
- token ID or equivalent audit correlation where available.

The request context is immutable after authentication. A tenant or BU supplied in a body, query parameter, or arbitrary header cannot override the verified context. If the caller belongs to multiple BUs, the requested active BU is accepted only after server-side membership verification. A missing, malformed, inactive, or cross-tenant BU is rejected.

## 4. PostgreSQL isolation contract

1. Every tenant-scoped read and write runs inside an explicit database transaction.
2. Immediately after transaction start, bind the verified tenant ID and active BU ID using transaction-local PostgreSQL settings (`SET LOCAL` or equivalent parameterized `set_config(..., true)`).
3. RLS policies derive scope only from those transaction-local settings. Missing settings resolve to no access; never fall back to an unrestricted query.
4. Policies enforce both tenant and BU boundaries for BU-scoped rows. Tenant-wide administrative access, if later required, must be a separate explicit policy and permission—not an implicit NULL or wildcard.
5. Application database roles must not own protected tables, be superusers, or have `BYPASSRLS`. Enable and force RLS on protected tables.
6. Migration/owner roles are separate from runtime application roles. Runtime credentials must not be able to disable RLS or alter policies.
7. Transaction context must be reset automatically at transaction end. Connection-pool reuse must never leak tenant or BU context across requests.
8. Background jobs must carry a signed/verified job identity and re-establish tenant/BU context in their own transaction; request context must never be reused implicitly.

## 5. Required adversarial test matrix

Run against a real PostgreSQL service in CI, not SQLite or mocks alone.

- Tenant A cannot read, update, or delete Tenant B rows.
- BU A cannot read, update, or delete BU B rows within the same tenant.
- A principal with multiple authorised BUs can access only the selected active BU.
- Forged tenant/BU request fields and headers do not change database scope.
- Missing tenant setting, missing BU setting, malformed setting, and absent transaction all fail closed.
- A pooled connection used by Tenant A cannot expose A's context to a subsequent Tenant B transaction.
- Runtime role cannot bypass RLS, own protected tables, or disable/alter policies.
- Inserts with mismatched tenant/BU values are rejected or invisible according to the documented policy.
- Rollback and exception paths clear transaction-local context.
- Expired, invalid-signature, wrong-issuer, wrong-audience, unsupported-algorithm, and unknown-key tokens are rejected.

Each test must assert both the response/exception and the rows visible or changed in PostgreSQL.

## 6. Implementation sequence

1. Agree the provider-neutral OIDC contract and claim-to-membership mapping.
2. Add typed identity configuration and strict JWT/JWKS validation.
3. Add principal resolution and server-side tenant/BU membership lookup.
4. Add SQLAlchemy/psycopg transaction boundary and transaction-local context binding.
5. Add versioned migrations for membership tables, runtime/migration roles, and a minimal BU-scoped test domain table.
6. Add forced RLS policies and least-privilege grants.
7. Add PostgreSQL-backed adversarial tests and CI service configuration.
8. Run Ruff, Mypy, unit tests, PostgreSQL integration tests, dependency lock validation and security review.
9. Obtain independent review of the exact final commit before merge.

## 7. Acceptance criteria

- No protected endpoint can execute without a verified principal and resolved tenant/BU membership.
- No tenant-scoped SQL executes outside a transaction with transaction-local context.
- RLS is enabled and forced on every protected table.
- Runtime DB role is demonstrably unable to bypass RLS.
- All adversarial tests above pass against PostgreSQL.
- CI is green on the exact PR head.
- Reviewer confirms no context leakage, cross-tenant/BU access, or privilege escalation path.
- No unsupported claim of production certification.

## 8. Explicit unresolved deployment inputs

The following are customer/deployment decisions and must be configurable, not guessed:
- OIDC issuer and audience.
- JWKS discovery/endpoint and key-rotation expectations.
- Claim names or membership source used to identify users.
- Initial role/permission mapping.
- PostgreSQL version and deployment topology.
- Whether a customer requires multiple active BU contexts per request (default: one active BU per transaction).

Until these decisions are configured and the acceptance tests pass, identity/RLS must be described as planned or in development—not implemented or certified.
