# PowerOps 0.1.1 — Identity, Tenant Context and PostgreSQL RLS Design Gate

Status: **DESIGN REVISION — NOT IMPLEMENTED — INDEPENDENT REVIEW REQUIRED**
Baseline: `258d6f963aa7cca518800d196c40f3f6fdf22943`
Original reviewed design: `7ec930970dcc594a627a68f59ad60632c38035d6`
Target release: `0.1.1`
Working branch: `feat/0.1.1-identity-tenant-rls`

## 1. Objective, threat model and release boundary

Introduce a provider-neutral identity boundary, server-verified tenant and business-unit (BU) membership, and PostgreSQL-enforced row isolation. Protected operations fail closed when identity, membership, database identity, or transaction state is absent or invalid.

### 1.1 Threats this design must address

The security design must address:
- Malicious users supplying forged tenant, BU, role, or principal identifiers.
- Application defects that omit tenant/BU predicates.
- SQL injection or arbitrary SQL execution under the application's ordinary database login.
- Attempts to change database roles, access privileged functions, or exploit pooled connections.
- Stale or revoked user/job membership.
- Background-job payload tampering and replay.
- Cross-tenant and cross-BU reads, writes, deletes, and relational references.

**Important RLS limitation:** PostgreSQL custom configuration settings (including custom GUCs set with `SET LOCAL` or `set_config(..., true)`) are session-settable by an ordinary database session. Transaction-local scope prevents persistence across transactions; it does not authenticate the setter. Therefore, a shared runtime role plus RLS policies that trust caller-writable tenant/BU GUCs is NOT an acceptable isolation boundary against arbitrary SQL execution.

This revision removes caller-writable GUCs as the source of RLS authority. GUCs may be used for diagnostics only and must never grant access.

### 1.2 Release boundary

This is a design proposal, not implementation or production certification. It does not add live utility integrations, operational control, SCADA/DMS write paths, or authorisation to operate a distribution network. PowerOps remains advisory-only.

## 2. Identity integration contract

1. Use provider-neutral OIDC/OAuth 2.0 access tokens intended for the PowerOps API. Do not accept OIDC ID tokens as API bearer tokens.
2. Configure the exact issuer, API audience, trusted discovery/JWKS location, and accepted token profile per deployment. Never accept issuer, audience, JWKS URL, or algorithm from a request or untrusted token header.
3. Validate the signature using keys obtained only from the configured issuer's trusted JWKS endpoint. Initially allow-list RS256 only unless a separately reviewed deployment profile explicitly adds another asymmetric algorithm. Reject `none`, symmetric algorithms, algorithm/key-type confusion, unsupported algorithms, invalid signatures, and inappropriate key use.
4. Validate exact issuer; API audience; required subject; token type/profile; `exp`; `nbf` when present/required by profile; and `iat` where required. Validate claim types and reject malformed or duplicate/ambiguous security claims. Reject tokens intended for another API/client and reject ID-token substitution.
5. Define a deployment-configured maximum access-token lifetime and bounded clock-skew allowance. The initial policy must use a small bounded skew (default 60 seconds, configurable only through reviewed deployment configuration); reject tokens with future issue times outside that allowance or lifetime exceeding the configured maximum.
6. Use issuer plus subject as the external principal key. Resolve it to an internal immutable principal ID. Email and display name are attributes, never principal identifiers.
7. Do not implement a local password store or custom authentication protocol in this milestone.
8. Missing or invalid identity configuration must prevent protected routes from starting in an authentication-enabled deployment. No production-mode development bypass is permitted.

## 3. JWKS trust, caching, rotation and revocation

1. Provision the issuer and JWKS trust configuration through an authenticated deployment/administrative process. Pin the expected issuer exactly. If OIDC discovery is used, the metadata issuer must exactly match the configured issuer; the discovered JWKS URI must satisfy the deployment's trusted endpoint policy.
2. Require HTTPS with normal certificate and hostname validation. Do not follow redirects to an untrusted host. Do not accept a JWKS URI, key, certificate, or `kid` mapping supplied by a request.
3. Validate JWK `kty`, `use`, `key_ops`, algorithm compatibility, key size and curve as applicable. For RS256, require an RSA signing key of at least 2048 bits.
4. Cache validated keys for a bounded deployment-configured period. On unknown `kid`, permit at most one rate-limited refresh per issuer/cache interval, then retry validation once. Unknown keys remain rejected.
5. On JWKS outage, use a previously validated, still-within-policy cached key only for the documented cache-staleness window. Once that window expires, fail closed; never accept an unverified token.
6. Document normal rollover: publish new key before use, overlap old/new keys for a defined period, then retire the old key. Document emergency compromise response: revoke/deny the affected key, force cache invalidation, and reject tokens signed by it. Emergency revocation must not wait for normal cache expiry.
7. Emit security audit events for unknown key IDs, invalid signatures, issuer/audience mismatch, key refresh failures, and emergency key revocation without logging bearer tokens.

## 4. Principal, membership and revocation contract

1. Resolve issuer-plus-subject to an internal principal and current server-side tenant/BU membership. Token claims alone do not grant tenant or BU authority.
2. Client-supplied tenant/BU values are selectors only. Every requested active tenant or BU is checked against current membership before the request is authorised.
3. Revalidate membership on every new request that establishes a protected database session. Membership cache, if used, must be bounded to a maximum 30-second TTL by default and invalidated on membership change where an event mechanism exists.
4. Revocation and permission changes must take effect within the documented maximum 30-second cache bound; high-risk deployments may require synchronous membership lookup with no positive cache. If membership authority is unavailable or freshness cannot be established, fail closed.
5. Recheck membership whenever the active tenant or BU changes. Never carry an old request context into a new request, transaction, or job.
6. A principal belonging to multiple BUs has one selected active BU per transaction by default. No NULL, wildcard, or omitted BU value may silently broaden access.
7. Audit membership grants, changes, revocations, active tenant/BU selection, denials, and administrative overrides. Administrative override must be a separate explicit permission and workflow, not a bypass in ordinary RLS.

## 5. Database trust boundary — no caller-writable tenant GUC authority

### 5.1 Required baseline: database login identity is the RLS authority

The baseline design for deployments requiring resistance to arbitrary SQL under the application login is **scope-bound PostgreSQL login roles**:

1. A database login identity is provisioned for one security scope: one tenant and one BU. The database's immutable `session_user` is the authority key used by RLS. The application must not use one shared database login that can access every tenant/BU.
2. A protected authorization mapping table maps each scope-bound login role to exactly one tenant ID and one BU ID (or to an explicitly defined tenant-wide scope for specifically authorised tenant-level operations). Mapping changes are performed only by a separate provisioning/migration authority.
3. RLS obtains tenant/BU scope from a narrowly scoped, audited, read-only `SECURITY DEFINER` lookup function that takes no caller-supplied tenant/BU arguments and derives the lookup key from `session_user`. It must not trust `current_user`, custom GUCs, request headers, or SQL parameters for scope.
4. The function owner is a dedicated NOLOGIN role with only the minimum SELECT privilege on the protected role-to-scope mapping. It is not superuser, has no `BYPASSRLS`, does not own protected business tables, and cannot modify the mapping. The function must schema-qualify objects, set a fixed safe `search_path` (including `pg_catalog` and only trusted schemas), avoid dynamic SQL, and have PUBLIC execute revoked. Grant EXECUTE only to the required runtime roles.
5. RLS policies use the function-derived scope and fail closed when the mapping is absent, duplicated, disabled, or invalid. The function returns no usable scope for an unmapped login. No caller-provided argument can select another scope.
6. The runtime login cannot `SET ROLE` to another tenant/BU login or inherit membership in another scope role. Do not grant cross-scope role memberships. The application must not connect as a shared privileged login and then switch roles.
7. Use separate connection pools keyed by database login/scope. A connection authenticated as one scope must never be repurposed as another scope by changing GUCs or `SET ROLE`. Credential rotation and pool retirement are required when scope credentials change.
8. This model contains arbitrary SQL executed under a scope-bound login to that login's authorised tenant/BU scope; it does not make SQL injection harmless. It must not permit the attacker to forge another scope. Least-privilege table/function grants must further limit damage within the authenticated scope.

### 5.2 Deployment scalability and alternatives

Scope-bound login roles introduce credential and pool-management overhead. That is an explicit trade-off, not a reason to silently fall back to shared-role GUC authority.

For deployments where per-scope database logins are operationally unsuitable, use a stronger isolation topology such as a separate database per tenant (and, where BU isolation requires it, a separately isolated database/schema or equivalent independently authenticated database principal). The alternative must be documented and independently reviewed before use.

A signed-context broker or cryptographically verified context token may be proposed as an alternative only with a complete design proving that the runtime SQL session cannot forge or replay a context and cannot access the signing/verification secret or privileged setter. A caller-writable GUC carrying a plain tenant ID, HMAC generated by the application, or unsigned job payload is not sufficient.

### 5.3 Transaction requirements

1. Every protected operation runs in an explicit transaction on one transaction-bound connection.
2. RLS authority comes from `session_user` mapping, not transaction-local GUCs. Transaction-local diagnostic values may be recorded but cannot grant access.
3. All protected queries in a unit of work use the same authenticated scope-bound connection.
4. Rollback on exception, cancellation, timeout, or failed unit of work. Never return a connection with an open or failed transaction to the pool.
5. Session-level tenant/BU settings are prohibited as an authorisation mechanism. Context must not be changed with `SET ROLE`.
6. Background jobs establish a new connection authenticated for the job's verified tenant/BU scope and a new transaction; they do not inherit request connections.

## 6. PostgreSQL RLS policy and schema contract

For every protected table, document its scope type (tenant-wide or tenant-plus-BU) and apply explicit policies:

- SELECT: `USING` must match the authenticated tenant and, for BU-scoped rows, the authenticated BU.
- INSERT: `WITH CHECK` must require the new row's tenant and BU to match the authenticated scope.
- UPDATE: `USING` must restrict which existing rows can be targeted, and `WITH CHECK` must restrict the resulting row. Both tenant and BU must remain in scope.
- DELETE: `USING` must restrict deletions to the authenticated scope.
- No policy may use NULL, empty string, wildcard, or missing context as an all-tenant/all-BU condition.
- Enable and FORCE RLS on every protected table. Runtime roles must not own protected tables, be superusers, or have `BYPASSRLS`.
- Use composite foreign keys and constraints to ensure a BU belongs to the same tenant as every row referencing it. A valid BU ID from another tenant must not be attachable to a row.
- Define tenant-wide administrative access separately, with explicit role, policy, audit event and tests. Do not encode it as a wildcard in the ordinary BU policy.
- RLS is not a substitute for ordinary grants, validation, constraints, or secure query construction.

## 7. Runtime privilege matrix and privileged paths

The migration/owner role and runtime role must be distinct. Runtime role privileges must be explicitly enumerated and tested.

Runtime roles:
- Must not own protected tables, schemas, or authorization mapping objects.
- Must not be superuser, have `BYPASSRLS`, or inherit/assume another scope's role.
- Must not have DDL privileges, policy alteration privileges, schema CREATE privileges in trusted schemas, or access to migration credentials.
- Must not have TRUNCATE on protected tables; TRUNCATE is not filtered by ordinary row-level policies.
- Must receive only required table-level SELECT/INSERT/UPDATE/DELETE grants and narrowly scoped function EXECUTE grants.
- Must not access secret stores, role provisioning credentials, migration functions, or privileged maintenance functions.
- Must not execute unreviewed `SECURITY DEFINER` functions.

Every SECURITY DEFINER function must have an explicit owner, fixed safe search_path, schema-qualified object references, minimal grants, no unsafe dynamic SQL, and tests for privilege escalation. Review inherited role memberships and `SET ROLE` attempts, including indirect membership. Protect schema, function, sequence and REFERENCES privileges as appropriate. The deployment must inventory extensions and privileged functions available to the runtime role.

## 8. Background-job identity and replay controls

1. Queue payload fields such as tenant ID, BU ID, principal ID, or role are data, not authority.
2. A trusted job issuer signs a canonical job envelope containing issuer, subject/service identity, tenant, BU, job type, audience, issued-at, expiry, unique job ID and permitted operation scope.
3. Workers verify signature against pinned job-issuer keys, exact issuer/audience, allowed job type, expiry and permitted operation. Define key rotation and emergency revocation.
4. Enforce one-time/replay protection using a durable job ID/idempotency record with atomic claim semantics. Reject duplicate, expired, altered, or wrong-audience jobs.
5. At execution time, revalidate the service/principal's current tenant/BU membership and job permission. Define whether user revocation cancels queued work; default: user-delegated jobs are rejected if the delegating user's membership or permission is revoked before execution. Service-owned jobs require an independently authorised service identity.
6. Establish a new scope-bound database connection and transaction for each job. Never trust queue-supplied scope without matching it to the verified signed envelope and current membership.
7. Audit issuer, job ID, scope, job type, authorization result, execution result and replay rejection without logging secrets.

## 9. Bearer-token replay and transport

Require TLS for all API traffic and secure transport between application services and identity/JWKS endpoints. Access-token lifetime must be bounded by deployment policy. Define logout/revocation behaviour and document that ordinary bearer tokens can be replayed by anyone who steals them until expiry or revocation takes effect.

For higher-risk customer deployments, assess sender-constrained access tokens (mTLS or DPoP) and define when they are mandatory. Do not claim bearer-token replay prevention unless sender-constraining and server-side replay controls are implemented and tested.

## 10. Required adversarial test matrix

Run against real supported PostgreSQL versions in CI, not SQLite or mocks alone. Tests must assert actual persisted rows, visible rows, changed rows, effective database identity, and grants—not HTTP status alone.

### Identity and JWKS
- Wrong issuer, audience, token type, ID-token substitution, malformed claims/types, missing subject, invalid signature, expired token, future `nbf`/`iat`, excessive lifetime, unsupported algorithm, `none`, symmetric algorithm, algorithm/key-type confusion.
- Unknown `kid`, bounded refresh/rate limit, JWKS outage, stale cache expiry, normal key rollover, emergency key revocation, wrong JWKS endpoint/redirect/issuer metadata, undersized RSA key and inappropriate JWK use.

### Membership
- Unauthorised tenant/BU selector, revoked membership while token remains valid, permission downgrade, membership-store outage, cache expiry/invalidation, BU switch, multiple BU membership, cross-tenant BU reference and administrative override audit.

### Database identity and RLS
- Tenant A login cannot read, update, delete or insert into Tenant B.
- BU A login cannot read, update, delete or insert into BU B in the same tenant.
- Attempt to forge tenant/BU through custom GUCs, `SET LOCAL`, `set_config`, request headers, SQL parameters and direct SQL under the runtime login; scope must remain that of immutable `session_user`.
- Attempt `SET ROLE`, inherited role escalation, `TRUNCATE`, DDL, policy alteration, migration credential access and privileged function execution; each must be denied.
- Missing or unmapped `session_user` fails closed.
- UPDATE changing tenant ID or BU ID is rejected by WITH CHECK.
- INSERT with mismatched tenant/BU is rejected.
- Cross-tenant composite foreign-key references are rejected.
- Runtime cannot read or alter the role-to-scope mapping table directly.
- SECURITY DEFINER function cannot be abused through search_path manipulation, untrusted objects, dynamic SQL or caller-supplied scope.
- Tenant-wide access is denied to ordinary BU roles and permitted only to explicitly authorised administrative roles.

### Pooling, concurrency and jobs
- Concurrent requests on different scope-bound pools cannot cross-read or cross-write.
- Connection reuse after rollback, exception, timeout and cancellation preserves authenticated session_user scope.
- No connection returns to pool with an open/failed transaction.
- Session-level GUC changes do not affect RLS authority.
- Job payload tenant/BU tampering, signature failure, wrong audience/type, expiry, duplicate job ID/replay, key rotation, membership revocation before execution and cross-scope DB connection attempts are rejected.
- Each job establishes its own transaction and scope-bound connection.

## 11. Implementation sequence after design approval

1. Confirm customer deployment topology and scope-bound login provisioning strategy.
2. Finalise OIDC access-token profile, trusted issuer/JWKS configuration and key lifecycle.
3. Implement principal resolution and membership freshness/revocation.
4. Implement secure database role provisioning and immutable login-to-scope mapping.
5. Implement narrowly scoped SECURITY DEFINER scope lookup with fixed search_path and explicit grants.
6. Add versioned migrations, runtime/migration role separation, composite tenant/BU constraints and forced RLS policies.
7. Add scope-keyed connection pools and transaction-bound repository/service operations.
8. Add signed job envelope, replay protection and worker-side membership verification.
9. Add PostgreSQL adversarial integration tests and CI service configuration.
10. Obtain independent implementation security review of the exact final commit before merge.

## 12. Acceptance criteria for design approval

- The design explicitly acknowledges that caller-writable custom GUCs are not trusted authentication evidence.
- RLS derives scope from immutable database login identity or an independently reviewed equivalent trust boundary.
- Arbitrary SQL under one scope-bound runtime login cannot forge another tenant/BU scope.
- Runtime roles cannot assume another scope or reach privileged database paths.
- OIDC access-token and JWKS trust/rotation contracts are complete.
- Membership freshness and revocation have measurable bounded behaviour and fail closed.
- Exact SELECT/INSERT/UPDATE/DELETE policy semantics and tenant/BU relational constraints are specified.
- Background jobs have signed identity, audience, expiry, replay protection and execution-time membership checks.
- The expanded adversarial test matrix is accepted by the independent reviewer.
- No unsupported claim of implementation or production certification is made.

## 13. Customer deployment inputs and explicit decisions

The following must be configured and documented per customer deployment:
- OIDC issuer, API audience, access-token profile and required claims.
- Trusted discovery/JWKS endpoint, cache bounds, rollover and emergency revocation process.
- Principal-to-membership source and maximum membership freshness/revocation window.
- PostgreSQL version/topology and supported connection-pool implementation.
- Scope-bound login provisioning, secret rotation, pool lifecycle and maximum tenant/BU scope count.
- Tenant-wide administrative roles and their approval/audit requirements.
- Job issuer, signing-key lifecycle, replay store and delegated-job revocation policy.
- Whether a separately isolated database topology is required for scale or assurance.

Until design approval, implementation, PostgreSQL adversarial tests and independent implementation review are complete, identity/RLS must be described as planned or in development—not implemented, certified, or production-ready.
