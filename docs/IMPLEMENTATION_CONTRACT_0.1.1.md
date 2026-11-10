# PowerOps 0.1.1 — Implementation Contract and Security Acceptance Matrix

**Status:** specification and test plan only  
**Design source:** PR #3, revised design commit 1cc39dcc5a7f3c355f4f230b6eeafd46ae018348  
**Independent decision:** APPROVED WITH CONDITIONS  
**Baseline:** 258d6f963aa7cca518800d196c40f3f6fdf22943  
**Release posture:** no implementation approval, deployment, production certification or operational activation is implied.

## 1. Purpose

Translate reviewer conditions C-01 through C-07 into an ordered implementation contract and adversarial acceptance matrix. This is a separate implementation-planning artifact; PR #3 remains the design-review record.

In scope: OIDC access-token validation, membership/revocation, PostgreSQL scope-bound login identities, protected role-to-scope mapping, RLS, database privileges, SECURITY DEFINER hardening, scope-aware pools, long-running work, background jobs, topology, scale and real PostgreSQL tests.

Out of scope: SCADA/DMS commands, dispatch, switching, protection settings, live utility integrations, customer production data, deployment and certification.

## 2. Non-negotiable invariants

1. Effective database scope is derived from authenticated PostgreSQL session_user mapped to exactly one active scope. Request headers, JWT claims, SQL parameters, SET variables and caller-writable GUCs are not database authority.
2. No shared cross-tenant or cross-BU runtime login. Each database login is bound to one explicit security scope.
3. Tenant-wide access, if required, is an explicit separate scope; it is never inferred from missing BU context.
4. Unmapped, disabled, revoked, stale or ambiguous identities fail closed.
5. RLS protects SELECT, INSERT, UPDATE and DELETE. Composite tenant/BU constraints prevent cross-scope relationships.
6. Runtime roles cannot change identity, assume another scope, bypass RLS, truncate protected tables, run DDL or modify security mappings.
7. Pooling never retargets a connection by mutating session variables. Scope changes require a newly authenticated connection for that scope.
8. Background jobs are signed, audience-bound, expiring and replay-resistant; membership is revalidated at execution.
9. Acceptance tests inspect actual PostgreSQL identity and persisted rows, not only HTTP responses.
10. Security authority outages fail closed. PowerOps remains advisory-only.

## 3. C-01 — Role-to-scope mapping integrity

### Implementation requirements
- Key the protected mapping by PostgreSQL role OID, not role name alone. Role name may be retained only for diagnostics.
- Enforce exactly one active scope per login role OID. Scope includes tenant ID and an explicit BU discriminator; tenant-wide scope is explicit.
- Mapping table is owned by a dedicated provisioning/migration authority. Runtime roles have no INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES or ownership privileges.
- The lookup function receives only the minimum SELECT capability; it cannot modify mapping state.
- Provisioning is atomic: create role, configure credentials, insert mapping, apply least-privilege grants, validate, then activate.
- Deprovisioning disables/revokes access, invalidates sessions and pools, then removes mapping.
- Role rename preserves OID and scope. Drop/recreate produces a new OID with no inherited mapping. Credential rotation preserves scope but revokes old credentials.
- Role memberships must not permit cross-scope SET ROLE or inherited privileges.

### Acceptance tests
| ID | Attack/test | Required result |
|---|---|---|
| C01-01 | Runtime reads mapping table | Permission denied |
| C01-02 | Runtime mutates/truncates mapping | Permission denied |
| C01-03 | One role OID assigned two active scopes | Constraint/provisioning rejection |
| C01-04 | Rename mapped role | OID retains same scope |
| C01-05 | Drop and recreate same role name | New OID is unmapped; fail closed |
| C01-06 | Unknown login OID | No scope; request denied |
| C01-07 | Cross-scope SET ROLE/inherited membership | Impossible for runtime |
| C01-08 | Provisioning interrupted mid-flight | Atomic rollback; no partial active identity |
| C01-09 | Credential rotation | New credential same scope; old credential rejected |
| C01-10 | Deprovision while sessions exist | New work denied; affected sessions/pools invalidated |

## 4. C-02 — SECURITY DEFINER hardening

### Implementation requirements
- Dedicated function owner: NOLOGIN, NOSUPERUSER, NOBYPASSRLS; no interactive credentials.
- Fixed trusted search_path; schema-qualify object references. No schema writable by untrusted roles may appear in the search path.
- No dynamic SQL. Any proposal to introduce it requires a separate security review.
- Function derives scope from session_user and role OID. It accepts no tenant, BU, role name or scope ID argument.
- Return only the minimum scope tuple required by RLS.
- Revoke EXECUTE from PUBLIC; grant only to intended runtime roles.
- Function owner does not own application tables and has no broad write privilege.
- Untrusted roles cannot CREATE objects in trusted schemas.
- Validate hostile search_path, temporary-object shadowing, grants and function ownership in migrations and drift checks.

### Acceptance tests
| ID | Attack/test | Required result |
|---|---|---|
| C02-01 | PUBLIC invokes function | EXECUTE denied |
| C02-02 | Hostile search_path | Correct scope; no shadowing |
| C02-03 | Same-named temporary object | Attacker object ignored |
| C02-04 | Runtime creates object in trusted schema | Permission denied |
| C02-05 | Inspect function owner | NOLOGIN, NOSUPERUSER, NOBYPASSRLS |
| C02-06 | Inspect function contract | No caller-supplied scope or unsafe dynamic SQL |
| C02-07 | Runtime alters function/mapping | Permission denied |
| C02-08 | SECURITY DEFINER escalation attempt | Denied |
| C02-09 | Fresh install and migration grant audit | PUBLIC revoked; only intended grants |

## 5. C-03 — Revocation and long-running work

### Implementation requirements
- Default maximum positive membership-cache/revocation bound for new protected work: 30 seconds, unless stricter policy applies.
- Explicitly distinguish new-work revocation from termination of already-running transactions, queries, sessions and jobs. A 30-second cache bound does not terminate in-flight work.
- Define configurable hard maximums for protected transaction, query and job duration before release.
- Revalidate membership at each protected unit of work and immediately before background-job execution.
- Revocation triggers pool eviction and, where required, cancellation/termination of affected sessions and work.
- Document whether an in-flight write is cancelled/rolled back or allowed to complete within a bounded policy. No silent indefinite continuation.
- Authority outage or stale cache beyond policy fails closed.
- Audit revocation, rejected work, pool eviction, cancellation and in-flight completion.

### Acceptance tests
| ID | Attack/test | Required result |
|---|---|---|
| C03-01 | Revoke membership; submit new request | Denied within configured propagation bound |
| C03-02 | Revoke during open transaction | Documented rollback/cancellation policy enforced |
| C03-03 | Revoke during long query | Query cancelled within configured maximum |
| C03-04 | Revoke queued job | Rejected at execution |
| C03-05 | Revoke running job | Cancellation checkpoint prevents further protected work |
| C03-06 | Membership authority unavailable after cache expiry | Fail closed |
| C03-07 | Exceed transaction/query/job duration | Terminated and audited |
| C03-08 | Revocation triggers pool eviction | Affected scope connections removed |
| C03-09 | Inspect state after cancellation | No partial unauthorised write |

## 6. C-04 — Exact OIDC access-token profile

### Implementation requirements
- Build a provider-neutral OIDC integration contract. Do not hard-code Microsoft Entra ID, Google, Keycloak or any other vendor as the required identity provider.
- Support any provider that conforms to the agreed OIDC/OAuth 2.0 security profile and publishes trusted discovery/JWKS metadata through an approved configuration path. Provider compatibility must be established by conformance tests, not by vendor name alone.
- Keep provider-specific behavior in isolated adapters/configuration profiles: issuer and discovery URL, expected audience, claim mapping and types, token type, azp rules, scopes, JWKS refresh/rotation behavior and documented deviations. The core token validator and authorization policy must remain provider-independent.
- Configure issuer, audience, client/resource identifiers, allowed algorithms, claim mappings and trust anchors per deployment through validated configuration/secrets. Never accept arbitrary issuer/JWKS URLs supplied by an end user or an untrusted token.
- Do not weaken mandatory validation to accommodate a provider. A provider that cannot satisfy the security profile is not supported until an explicit, independently reviewed adaptation is designed.
- If IBDEC selects a non-OIDC or non-conforming identity service (for example, a SAML-only service), use an approved federation/identity broker to present a conforming OIDC interface, or undertake a separate security design review. Do not silently treat SAML assertions as OIDC tokens.
- IBDEC's eventual provider choice is a deployment configuration decision; it is not a prerequisite for building the provider-neutral adapter boundary and automated conformance harness.
- Document a provider-specific token profile for every enabled deployment; do not assume claim formats are identical.
- Accept access tokens only; reject ID tokens and tokens intended for another client/API.
- Validate exact issuer, expected audience and documented audience-array semantics, signature, algorithm, key type/strength, subject, token type/typ, exp, iat and nbf.
- Define provider-specific azp requirements and validate where applicable.
- Enforce maximum token lifetime and clock skew. Default maximum skew is 60 seconds; exceptions require documented evidence and review.
- Reject missing, malformed, wrongly typed, future-issued, expired and overlong tokens.
- JWKS trust, bounded cache/refresh, rollover, unknown-KID handling and emergency revocation must fail closed; no unbounded refresh or fail-open behavior.

### Acceptance tests
| ID | Attack/test | Required result |
|---|---|---|
| C04-01 | Valid configured access token | Accepted |
| C04-02 | ID token substituted for access token | Rejected |
| C04-03 | Wrong issuer/audience | Rejected |
| C04-04 | Audience array | Exact provider policy enforced |
| C04-05 | Missing/wrong-type required claim incl. azp where required | Rejected |
| C04-06 | Expired, not-yet-valid or future-issued token | Rejected |
| C04-07 | Lifetime exceeds configured maximum | Rejected |
| C04-08 | Clock skew exceeds configured maximum | Rejected |
| C04-09 | none/disallowed algorithm, weak key or algorithm confusion | Rejected |
| C04-10 | Unknown KID/JWKS unavailable | Bounded refresh then fail closed |
| C04-11 | Emergency-revoked signing key | Token rejected |
| C04-12 | Key rollover | Only configured trusted keys accepted |
| C04-13 | Run common OIDC conformance suite against each candidate provider | Provider passes mandatory security profile before enablement |
| C04-14 | Change provider configuration in staging | No core authorization/database redesign; old trust removed and new trust explicitly validated |
| C04-15 | Provider emits unsupported claim format or token type | Adapter rejects until reviewed mapping/profile is approved |
| C04-16 | Attempt to inject untrusted issuer/discovery/JWKS URL | Configuration rejected; no token-directed trust |
| C04-17 | Candidate is SAML-only/non-conforming OIDC | Requires approved federation broker or separate security design; no direct acceptance |

## 7. C-05 — Enterprise roles, credentials and pool scalability

### Implementation requirements
Publish a capacity profile before implementation completion: tenant count, BUs per tenant, active scopes, concurrent users/requests/transactions, role count, provisioning throughput, per-scope pool size and global connection budget. Document pooler product/version/mode, admission control, credential rotation, eviction and monitoring.

Initial architecture remains scope-keyed pools with one authenticated DB login per security scope. If a selected pooler cannot preserve required session_user semantics, it is not an approved configuration. Do not fall back to shared login plus writable GUC.

### Acceptance tests
| ID | Attack/test | Required result |
|---|---|---|
| C05-01 | Load at declared tenant/scope target | Meets documented limits |
| C05-02 | Exhaust one scope pool | Backpressure isolated to that scope |
| C05-03 | Exhaust global connection budget | Predictable admission control; no identity downgrade |
| C05-04 | Reuse connection within same scope | Correct identity; transaction state reset |
| C05-05 | Attempt reuse across scopes | Prohibited; no crossover |
| C05-06 | Test actual pooler mode | session_user semantics proven or configuration rejected |
| C05-07 | Rotate credentials under load | Old connections drained; old credentials rejected |
| C05-08 | Provision/deprovision at target churn | Atomic and within documented limits |
| C05-09 | Fail during cleanup | Dirty connection discarded, never returned to pool |

## 8. C-06 — Tenant/BU deployment topology

Before production topology selection, record an architecture decision comparing:

**Option A — shared database with scope-bound login roles:** RLS and per-scope pools as above; explicit role/connection scalability limits; tenant-wide access remains a separate explicit scope.

**Option B — separate database per tenant:** independent credentials and authenticated database boundary per tenant; BU policy still explicitly enforced within each tenant DB; define migrations, backup/restore, DR, monitoring, connection limits and cross-tenant analytics.

A separate schema in a shared database is not equivalent to an independent authenticated database boundary. The decision record must state selected topology, threat assumptions, guarantees, operational cost, scale and recovery. No production tenant data before review.

| ID | Required evidence | Pass criterion |
|---|---|---|
| C06-01 | Architecture decision record | Choice and rejected alternatives documented |
| C06-02 | Tenant/BU threat model | Trust boundaries and residual risks explicit |
| C06-03 | Migration/rollback rehearsal | Repeatable, scoped and auditable |
| C06-04 | Backup/restore test | No cross-tenant exposure |
| C06-05 | DR/failover rehearsal | Isolation controls remain enforced |
| C06-06 | Cross-tenant analytics design | No runtime bypass/shared privileged path |
| C06-07 | Capacity/cost model | Meets declared scale and recovery targets |

## 9. C-07 — Real PostgreSQL adversarial evidence

All security tests must run against supported PostgreSQL with production-equivalent roles, grants, policies, settings and selected pooler mode. SQLite, mocks, mocked RLS, unit-only tests and HTTP status assertions are insufficient.

Seed at least two tenants and two BUs per tenant with uniquely identifiable rows. Use actual database login roles per scope. Capture session_user, current_user, role memberships and transaction identity. Assert query results and persisted state after every attack. Include deterministic concurrent requests and connection reuse. Retain PostgreSQL version/configuration, migration version, SQL, test reports and CI run IDs. Fail if required database/pooler tests are skipped.

| ID | Attack/test | Required database evidence |
|---|---|---|
| C07-01 | Tenant A reads Tenant B | No rows returned |
| C07-02 | BU A reads BU B within same tenant | No rows returned |
| C07-03 | Cross-scope INSERT | Rejected; no row persisted |
| C07-04 | Cross-scope UPDATE/key rewrite | Rejected; original row unchanged |
| C07-05 | Cross-scope DELETE | No unauthorised deletion |
| C07-06 | Composite tenant/BU FK mismatch | Constraint rejects |
| C07-07 | SET ROLE / SET SESSION AUTHORIZATION | Cannot assume another scope/identity |
| C07-08 | BYPASSRLS, TRUNCATE, DDL, ownership escalation | Permission denied |
| C07-09 | Mapping tamper and role recreation | Runtime cannot alter mapping; new OID unmapped |
| C07-10 | Hostile search_path/temp object | No shadowing/escalation |
| C07-11 | Concurrent cross-scope pool reuse | No identity or row leakage |
| C07-12 | Revocation during long-running work | Configured cancellation/rollback verified |
| C07-13 | Job replay, expiry, wrong audience | Invalid/duplicate job rejected |
| C07-14 | Job tenant/BU mismatch | Execution denied and audited |
| C07-15 | Runtime attempts migrations | Permission denied |
| C07-16 | Inspect actual DB identity | session_user matches expected scope login |
| C07-17 | RLS inventory | Every protected table has expected RLS/force/policies |
| C07-18 | Post-attack persisted-state audit | No cross-scope disclosure or mutation |

## 10. Ordered engineering gates

| Gate | Work package | Exit criteria |
|---|---|---|
| 0 | Resolve provider, topology, scale, pooler and duration decisions | Decision record approved before implementation |
| 1 | Role OID mapping and atomic provisioning | C-01 tests pass |
| 2 | Protected scope lookup function | C-02 tests pass |
| 3 | RLS policies and composite constraints | Read/write adversarial tests pass |
| 4 | Provider-neutral OIDC adapter, provider conformance profiles/JWKS and membership | Core conformance suite passes; IBDEC's selected provider profile is separately validated before that deployment is enabled |
| 5 | Pool lifecycle and revocation | C-03/C-05 pass; no cross-scope reuse |
| 6 | Background-job identity | Signature, audience, expiry, replay and membership tests pass |
| 7 | Full PostgreSQL evidence | C-07 complete against actual supported topology |
| 8 | Independent implementation review | Exact SHA reviewed; critical/high findings closed |
| 9 | Separate release decision | Explicit approval; no automatic production promotion |

Split gates into separate PRs where that improves reviewability. Do not proceed downstream on a failed gate.

## 11. Evidence and release boundary

For every gate retain exact commit SHA, PR, workflow run/job IDs, PostgreSQL and pooler versions/modes, migrations, schema and role/grant/policy inventory, test reports, persisted-state assertions, threat model and reviewer decision. CI quality success is necessary but not proof of security.

This contract does not authorise merging PR #3, production deployment, live utility/customer data, SCADA/DMS connectivity, operational commands, switching, dispatch, protection actions or production certification. Those require completed implementation, adversarial evidence, independent security review, qualified power-systems review and separate release approval.

## 12. Gate 0 decisions required

The engineering owner must record:
1. **Provider choice is deferred:** implement the vendor-neutral OIDC adapter and common conformance suite now. When IBDEC confirms its identity provider, validate and approve that provider's exact access-token profile before enabling it in the IBDEC deployment. If the chosen service is not OIDC-conforming, decide on a federation broker or a separately reviewed design.
2. Initial maximum tenant count, BUs per tenant, active scopes and concurrent protected connections.
3. PostgreSQL version(s), pooler product/version and pooling mode to be tested.
4. Maximum transaction, query and background-job duration; in-flight revocation policy.
5. Initial topology: shared DB with scope-bound roles or separate DB per tenant.
6. Owners and runbooks for provisioning, credential rotation, emergency revocation and disaster recovery.

No implementation shortcut may weaken Section 2 invariants to avoid these decisions. Provider selection is not a blocker for the provider-neutral adapter design; it is a mandatory enablement decision before connecting IBDEC's live identity service.
