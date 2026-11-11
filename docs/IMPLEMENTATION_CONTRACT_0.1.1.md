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
- Key the protected mapping by the composite `(cluster_identity, role_oid)`, never by role name or role OID alone. `cluster_identity` is a stable, independently provisioned identity for one PostgreSQL cluster lifecycle; `role_oid` is interpreted only within that cluster. Role name may be retained only for diagnostics. Clone/restore identity lifecycle and duplicate-cluster fencing are governed by Section 20.
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
- Contract-wide hard ceiling for positive membership-cache lifetime before admitting new protected work: 30 seconds. A deployment may select a stricter value; it may not select a longer value under this contract.
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
- Enforce maximum token lifetime and clock skew. The 60-second clock-skew value is a provisional baseline default, not an automatically approved deployment value or a hard contract ceiling. Each deployment must set and approve its actual maximum; any value above 60 seconds requires a documented security exception, clock-synchronisation evidence and independent security approval. Missing or untrustworthy time synchronisation fails closed.
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

**Option B — separate databases within one PostgreSQL cluster:** distinct database names and tenant-specific login credentials, with explicit CONNECT/object privileges and tenant/BU RLS controls. PostgreSQL roles remain cluster-wide, so databases do not create independent role namespaces or independent cluster-administration boundaries. Define migration, backup/restore, DR, monitoring, connection limits and cross-tenant analytics.

**Option C — separate PostgreSQL clusters or independently administered instances:** separate cluster-level role namespaces, credentials, administration and recovery boundaries. Define network isolation, provisioning, patching, monitoring, backup/restore, DR, cross-cluster analytics and operational cost.

A separate schema in a shared database is not equivalent to an independent authenticated database boundary. Separate databases in one cluster are also not equivalent to separate clusters: PostgreSQL roles are cluster-wide. The decision record must compare all three options, state selected topology, threat assumptions, guarantees, operational cost, scale and recovery. No production tenant data before review.

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


## 13. Independent implementation-contract review conditions (IC-01–IC-07)

**Review decision on baseline:** APPROVED WITH CONDITIONS  
**Exact reviewed baseline:** `b63a341695960c93ae1f80479a9c9eaa2eaed312`  
**Disposition:** The following conditions are mandatory additions to the relevant gate exit criteria. They do not constitute implementation evidence or production approval.

### IC-01 — Authenticated role identity, OID resolution and lifecycle safety (High)

The implementation must document and test the exact PostgreSQL mechanism used to resolve the authenticated `session_user` to the role OID used by the protected mapping. Do not claim that `session_user` itself exposes an OID: it exposes a role identity/name. The implementation must explicitly analyse the name-to-catalog-OID resolution step and its behavior across role deletion, recreation and stale sessions.

Mandatory requirements:

1. Resolve the authenticated `session_user` only through a trusted, schema-qualified PostgreSQL catalog lookup; never accept a role name or OID from the caller, request, JWT, SQL argument or GUC.
2. Treat a missing, ambiguous, disabled or inconsistent role resolution as no scope and fail closed.
3. Establish a permanent non-reuse policy for login role names (including a tombstone/retired-name registry controlled by provisioning), so an old authenticated session cannot resolve by name to a newly created role with the same name.
4. Deprovision in this order: mark mapping inactive and commit; reject new work; revoke/rotate credentials; terminate all sessions for that login; evict its pools; verify zero remaining sessions; remove/retire mapping and role; permanently reserve the retired role name. The exact order must be transactionally and operationally safe for the chosen deployment.
5. Provisioning must reject a retired role name. A recreated role must receive a new, never-before-used login name and OID, with no inherited mapping or privileges.
6. Document catalog permissions and ensure the lookup can read the required role identity/OID without granting runtime roles catalog access beyond what is necessary.
7. Include failure recovery for interruption at every deprovisioning step. A partially deprovisioned role remains inactive and unusable until reconciled.

If the chosen PostgreSQL version/architecture cannot prove safe authenticated-identity-to-OID resolution and stale-session invalidation, stop and obtain a separately reviewed identity-binding design; do not substitute a writable GUC or caller-provided role identifier.

Additional mandatory tests:
- C01-11: verify the lookup derives identity from `session_user` and resolves the current catalog OID through the documented trusted mechanism.
- C01-12: old session plus drop/recreate attempt under the same role name; name reuse is prohibited, and no old session can resolve to a new scope.
- C01-13: interrupt deprovisioning after each step; role remains inactive, cannot perform protected work, and recovery completes safely.
- C01-14: verify retired-name tombstones survive backup/restore and provisioning recovery.
- C01-15: missing catalog role resolution returns no scope and fails closed.

### IC-02 — Effective SECURITY DEFINER privilege proof (High)

Add a machine-verifiable privilege inventory to the migration/test evidence. It must inspect effective privileges and role memberships, not merely declared role attributes.

Prove that the dedicated function owner:
- Has only the mapping-table `SELECT` privilege required by the lookup, plus unavoidable minimum schema/function privileges.
- Cannot INSERT, UPDATE, DELETE or TRUNCATE the mapping; create/alter/drop roles; alter memberships; modify application tables; run migrations; or assume privileged roles.
- Has no direct or inherited membership that grants provisioning, migration, ownership, superuser or bypass-RLS capability.
- Does not own the mapping table or protected application tables.
- Can read the intended mapping under the actual mapping-table ownership and RLS configuration, without a hidden policy bypass or accidental denial.

Also prove PUBLIC and all unintended roles lack function EXECUTE. Test hostile caller `search_path`, `pg_temp` shadowing, trusted-schema CREATE restrictions and effective privilege escalation attempts. Capture the SQL output of privilege/catalog inspection in the retained evidence.

### IC-03 — Numeric revocation and execution limits (High)

Gate 0 must record numeric, enforceable values before revocation/long-running-work implementation is declared complete:

| Parameter | Required Gate 0 value |
|---|---|
| Maximum protected transaction duration | Explicit duration |
| Maximum protected query duration | Explicit duration |
| Maximum background-job duration | Explicit duration |
| Maximum revocation propagation for new work | Explicit duration |
| Maximum query cancellation time after revocation | Explicit duration |
| Maximum affected-session termination time | Explicit duration |
| Maximum membership positive-cache lifetime | At most 30 seconds unless a stricter value is selected |
| In-flight write policy | Roll back/cancel, or bounded completion with explicit justification and limit |

Acceptance tests must consume these approved values from deployment configuration and assert actual elapsed behavior; they must not invent test-local timeout values. The policy must state exactly what happens to a write already in progress at revocation. No indefinite continuation is permitted. Retain timestamps and transaction/persisted-state evidence proving the selected behavior.

### IC-04 — JWT access tokens versus opaque OAuth tokens (Medium)

The current OIDC/JWKS validation path supports signed JWT access tokens only. Explicitly reject opaque OAuth access tokens on this path; do not attempt to parse them as JWTs or silently accept them.

If IBDEC or another customer requires opaque tokens, introduce a separately reviewed introspection-based validation profile. That profile must specify authenticated introspection transport, endpoint trust and TLS/redirect policy, client authentication, response validation, caching limits, availability behavior, revocation freshness, outage fail-closed behavior and adversarial tests. It must not weaken the signed-JWT path.

Add provider conformance tests for:
- Discovery document issuer exactly matching the configured trusted issuer.
- JWKS endpoint TLS validation and redirect policy (reject unapproved cross-origin redirects).
- Trusted binding between configured issuer, discovery metadata and JWKS endpoint.
- Unknown-KID refresh rate limiting and bounded negative caching to prevent refresh amplification.
- Emergency signing-key revocation and cache invalidation.
- Provider-specific audience, audience-array, `typ`, `azp` and access-token representation differences.

“Provider-neutral” means multiple independently tested adapters conform to one common security contract; it does not mean all providers are assumed to behave identically.

### IC-05 — Numeric capacity profile and actual pooler proof (High)

Before Gate 5 is accepted, Gate 0 must record numerical targets for:
- Maximum tenants.
- Maximum BUs per tenant.
- Maximum active database scopes.
- Maximum concurrent protected connections/transactions.
- Per-scope pool minimum/maximum and global pool maximum.
- Maximum role/credential count.
- Provisioning and credential-rotation throughput.
- Pooler product, exact version, configuration and pooling mode.

Run integration tests against the exact selected pooler version and mode. Prove that `session_user` remains associated with the intended authenticated scope during connection checkout, transaction completion, reuse, cancellation, credential rotation and pool eviction. Transaction pooling is not presumed compatible. If the selected pooler cannot preserve the required database-authenticated identity semantics, reject that configuration or choose a separately reviewed architecture; never fall back to shared login plus writable GUC.

### IC-06 — Approved topology decision record (Medium)

Before production topology selection, create and approve a version-controlled architecture decision record that:
- Selects one of: shared database with scope-bound login roles/RLS; separate databases within one PostgreSQL cluster; or separate PostgreSQL clusters/independently administered instances.
- Records the rejected alternative and rationale.
- Defines tenant/BU threat assumptions, trust boundaries, credentials and network boundaries.
- Covers migration/rollback, backup/restore, disaster recovery, monitoring, connection limits, cross-tenant analytics, operational ownership and cost.
- States which BU controls remain within a tenant database if separate databases are chosen.
- Includes recovery and adversarial-test evidence for the selected topology.

A separate schema in a shared database must not be represented as an independent authenticated database boundary.

### IC-07 — Reproducible PostgreSQL security evidence (Medium)

Every completed security gate must retain a reproducible evidence bundle containing:
1. Exact source commit, PR, workflow run ID and job ID.
2. PostgreSQL version, build and relevant server configuration.
3. Exact migration IDs/checksums and schema version.
4. Database role, membership and effective privilege inventory.
5. SECURITY DEFINER function owner, definition, search_path and EXECUTE grants.
6. Mapping-table owner, privileges and RLS configuration.
7. RLS policy inventory for every protected table, including enabled/forced status and command coverage.
8. Executed adversarial SQL/scripts and complete test output.
9. Before-and-after persisted-row assertions for each attack.
10. Pooler product/version/mode and connection-reuse test evidence where applicable.

The lookup must explicitly use authenticated `session_user` identity, not `current_user` inside SECURITY DEFINER execution (where current_user is the function owner). Add a test that records both values inside the function and proves the authenticated session identity is the source of scope resolution. CI must fail if required PostgreSQL adversarial suites or evidence artifacts are skipped or absent. SQLite, mocks and HTTP-only assertions remain insufficient.

## 14. Revised gate exit criteria

These additions refine, rather than replace, the existing ordered gates:

| Gate | Additional mandatory exit condition |
|---|---|
| Gate 0 | Numeric transaction/query/job/revocation limits; numerical capacity profile; actual PostgreSQL/pooler target; topology ADR; provider support boundary (JWT access tokens only on the JWKS path) |
| Gate 1 | IC-01 authenticated identity-to-OID mechanism, permanent role-name non-reuse, stale-session invalidation and interrupted-deprovisioning tests pass |
| Gate 2 | IC-02 effective SECURITY DEFINER owner privilege inventory and hostile search_path/pg_temp tests pass |
| Gate 3 | RLS evidence bundle includes exact policy inventory and persisted-state assertions |
| Gate 4 | IC-04 JWT-only boundary, discovery/JWKS TLS and issuer binding, redirect controls, unknown-KID rate limiting and emergency revocation tests pass |
| Gate 5 | IC-03 approved numeric revocation/execution limits enforced; IC-05 exact pooler configuration and declared capacity tests pass |
| Gate 6 | Job-duration and in-flight revocation behavior use the approved Gate 0 limits |
| Gate 7 | IC-07 reproducible evidence bundle complete; CI blocks missing/skipped adversarial evidence |
| Gate 8 | Independent reviewer assesses exact implementation SHA and all IC-01–IC-07 evidence; critical/high findings closed |
| Gate 9 | Separate explicit release authorization; no automatic deployment or operational activation |

**No gate is passed by documentation alone.** Each gate requires its implementation, test execution and retained evidence. Where a Gate 0 value or architecture choice is not yet known, record it as OPEN; do not invent a value or mark the affected gate complete.

## 15. Independent review remediation — PR #5 reassessment

**Review decision:** APPROVED WITH CONDITIONS  
**Exact reviewed commit:** `9abab6afb04007a60b4816345a3bd5d2b207a6ad`  
**Review scope:** this documentation-only implementation contract and CI run #69.  
**Boundary:** these clarifications do not constitute implementation evidence, gate completion or production approval.

### IC-01-R1 — Retired OID and restore/reconciliation semantics (Medium)

Role-name tombstones remain mandatory, and the implementation must additionally maintain an auditable retired-identity record for every deprovisioned role OID. A retired OID must never be reactivated or rebound to a scope, even if PostgreSQL later assigns that numeric OID to a newly created role.

Provisioning must compare the newly assigned catalog OID against the retired-identity registry before creating an active scope mapping. If the OID is present in the retired registry, provisioning must fail closed and must not activate the role or create a scope mapping. The implementation team must demonstrate a safe, operationally supported way to recover from that collision; it must not silently delete or overwrite the tombstone.

Backup/restore and point-in-time recovery procedures must preserve and reconcile both retired role-name and retired-OID records before accepting protected traffic. If restored catalog state and the tombstone registry are inconsistent, protected identity resolution remains disabled until reconciliation is complete.

Additional acceptance tests:
- C01-16: deprovision a role and verify both its name and OID are retained in immutable/audited retired-identity records.
- C01-17: simulate a newly created role receiving an OID present in the retired registry; provisioning refuses activation and no scope mapping is created.
- C01-18: restore a backup with catalog/mapping/tombstone state deliberately inconsistent; protected work remains disabled until reconciliation, and no retired identity is rebound.
- C01-19: verify tombstones are not removed by ordinary provisioning, cleanup, migration or restore operations; removal requires a separately approved security procedure.

### IC-03-R1 — Gate 0 execution and revocation limits (High)

The values in Section 13 remain OPEN until approved by the engineering owner for the actual deployment profile. Before implementing or declaring Gate 5 or Gate 6 complete, record numeric maximums for transaction duration, query duration, job duration, new-work revocation propagation, query cancellation, session termination and membership positive-cache lifetime. Record the in-flight write policy and its maximum completion/rollback bound.

No defaults are to be presented as approved deployment limits. The 30-second positive-cache value remains a maximum unless a stricter value is selected; the actual approved value must be explicit. Tests must read the approved profile and measure elapsed behavior and persisted database state.

### IC-04-R1 — Discovery and JWKS endpoint transport (Medium)

Both the OIDC discovery-document endpoint and the JWKS endpoint must use validated HTTPS/TLS. Certificate validation is mandatory. Redirects must be disabled by default; if a deployment requires redirects, only explicitly approved same-origin redirects may be followed under a documented policy. Unapproved cross-origin redirects must be rejected.

The configured issuer, discovery document issuer and JWKS trust binding must be consistent. A discovery document must not be allowed to redirect trust to an unapproved JWKS host.

Additional acceptance tests:
- C04-18: invalid/expired TLS certificate at discovery endpoint — fail closed.
- C04-19: invalid/expired TLS certificate at JWKS endpoint — fail closed.
- C04-20: unapproved cross-origin redirect from discovery or JWKS — rejected.
- C04-21: discovery issuer mismatch or discovery metadata pointing to an untrusted JWKS endpoint — rejected.
- C04-22: approved same-origin redirect behavior, if enabled, matches the documented allowlist and cannot change trust origin.

### IC-05 — Gate 0 dependency reminder (High)

The numerical capacity profile and exact pooler product/version/configuration/mode remain OPEN deployment decisions. Gate 5 cannot pass until these are selected, recorded and tested against the actual pooler. A generic unit test or a test against a different pooler/version/mode is not sufficient evidence.

### IC-06-R1 — Define the separate-database boundary (Medium)

The topology ADR must distinguish these materially different options:

1. **Separate databases in one PostgreSQL cluster:** PostgreSQL roles are cluster-wide, not database-local. The ADR must define distinct tenant login roles/credentials, CONNECT and object privileges, network/application routing, administrative trust boundary, and demonstrate that one tenant's credentials cannot authenticate into or obtain scope in another tenant database.
2. **Separate PostgreSQL clusters/instances:** define independent authentication and administrative boundaries, credential ownership, network segmentation, patching, monitoring, backup/restore and disaster recovery responsibilities.

The ADR must state which option is selected and must not describe separate databases in one cluster as independent role namespaces or as equivalent to separate cluster administration. Acceptance tests must attempt cross-tenant authentication and access using each tenant's credentials and verify denial at the actual selected boundary.

### Consolidated disposition

| Finding | Severity | Disposition |
|---|---|---|
| IC-01-R1 | Medium | Clarification and tests added; implementation evidence remains required |
| IC-03-R1 | High | Gate 0 numeric decisions remain OPEN |
| IC-04-R1 | Medium | Discovery/JWKS transport requirements and tests added |
| IC-05 | High | Gate 0 capacity and exact pooler selection remain OPEN |
| IC-06-R1 | Medium | Same-cluster versus separate-cluster distinction added |

The contract remains a plan for controlled implementation. Gate 0 decisions must be supplied by the deployment owner; values must not be invented. No implementation gate passes by documentation alone.


## 16. Independent security re-review remediation — IC-01-R2 and remaining Gate 0 conditions

**Review decision:** APPROVED WITH CONDITIONS  
**Exact reviewed commit:** `0a58835a5a21b45fb597a169dd7671a0ebaa73fb`  
**Review scope:** Sections 2–15 and CI run #70.  
**Boundary:** This section is a documentation and acceptance-test refinement only. It is not implementation evidence or production approval.

### IC-01-R2 — Cluster-scoped role OID identity and independent tombstone durability (Medium)

PostgreSQL role OIDs are scoped to a PostgreSQL cluster and are not globally unique. Every retired role identity record must therefore use a stable cluster identity together with the role OID as its identity key:

`(cluster_identity, role_oid)`

The cluster identity must be stable across ordinary restart, backup and restore, and must not be inferred solely from a mutable hostname, IP address or display name. The deployment architecture must define how a newly provisioned cluster receives a distinct identity and how clone/restore procedures prevent accidental identity duplication.

The authoritative retired-identity registry must survive point-in-time restoration of the PostgreSQL cluster to a point before a role was deprovisioned. Keeping the only tombstone copy inside the database being restored is insufficient unless an independently recoverable mechanism proves that no retired record can be lost.

Requirements:
- Maintain an auditable retired-identity key containing stable cluster identity and role OID.
- Store or replicate authoritative tombstones in an independently recoverable system, or document and prove an equivalent mechanism with the same rollback-resistance guarantee.
- Restrict append, reconciliation and exceptional removal privileges to explicitly named security/provisioning authorities; ordinary runtime, provisioning, migration and restore identities cannot alter or delete retired records.
- Reconcile authoritative tombstones against the restored PostgreSQL catalog and role mappings before enabling protected traffic.
- If registry availability, integrity, cluster identity or reconciliation is uncertain, disable protected identity resolution and fail closed.
- Exceptional tombstone removal, if ever permitted, requires a separately approved, dual-controlled security procedure and immutable audit evidence.

Additional acceptance tests:
- C01-20: deprovision a role in cluster A and verify its retirement key includes cluster A's stable identity and role OID.
- C01-21: create/inspect cluster B with the same numeric role OID and prove it is not confused with cluster A's retired identity.
- C01-22: restore cluster A from a point-in-time backup predating deprovisioning while retaining the authoritative tombstone; protected resolution remains disabled until reconciliation completes.
- C01-23: attempt tombstone modification/deletion using runtime, provisioning, migration and restore identities; all unauthorised operations fail and are audited.
- C01-24: verify cluster identity remains stable across supported restore/recovery and is distinct for a separately provisioned cluster; cloned environments cannot accept protected traffic until identity is explicitly reconciled.
- C01-25: simulate unavailable, stale or inconsistent authoritative tombstone storage; all protected identity resolution fails closed.

### IC-04-R2 — Discovery/JWKS endpoint resolution restrictions (Low)

In addition to the HTTPS/TLS and redirect requirements in Section 15, endpoint resolution must be constrained by the deployment's approved network policy.

Requirements:
- Bind discovery and JWKS retrieval to explicitly approved hostnames and trust origins.
- Resolve and validate destination addresses at connection time; reject prohibited loopback, link-local, private, metadata-service or otherwise disallowed destinations unless a specific destination is explicitly approved for that deployment.
- Revalidate destination policy after DNS changes and redirects; do not allow DNS rebinding or redirect behavior to bypass the approved destination policy.
- Apply equivalent controls to IPv4 and IPv6 and to every resolved address used by the HTTP client.
- Do not disable certificate validation or destination checks to make a provider work; unsupported provider/network configurations require an explicit reviewed exception or alternative integration design.

Additional acceptance tests:
- C04-23: discovery hostname resolves to a prohibited loopback, link-local, private or metadata-service address; request rejected before metadata is trusted.
- C04-24: JWKS hostname resolves to a prohibited destination; signing keys are not fetched or trusted.
- C04-25: DNS answer changes from an approved to a prohibited address between refreshes; subsequent retrieval is rejected.
- C04-26: redirect to an unapproved hostname or prohibited destination; request rejected.
- C04-27: IPv4 and IPv6 resolution policy is consistently enforced.

### Gate 0 — decisions that remain OPEN

The reviewer confirmed that the contract requirements are substantially satisfied, but the following are deployment-owner decisions and must not be invented by the engineering team. Gate 0 remains OPEN until an approved, version-controlled deployment profile and topology ADR record them:

1. Initial maximum tenant count.
2. Maximum business units per tenant.
3. Maximum active database scopes.
4. Maximum concurrent protected connections/transactions.
5. Per-scope pool minimum/maximum and global connection budget.
6. Exact PostgreSQL version and deployment topology: shared database with scope-bound login roles, separate databases within one cluster, or separate PostgreSQL clusters/instances.
7. Exact pooler product, version, configuration and pooling mode.
8. Maximum protected transaction duration, query duration and background-job duration.
9. Maximum new-work revocation propagation, query-cancellation time and affected-session termination time.
10. Maximum positive membership-cache lifetime (no more than 30 seconds unless a stricter value is selected).
11. Explicit in-flight write policy: rollback/cancel or bounded completion with approved maximum duration and justification.
12. Provider support boundary: provider-neutral OIDC adapter and common conformance suite may be developed; the selected deployment provider profile must pass conformance before enablement. The JWKS validation path accepts signed JWT access tokens only unless a separately reviewed opaque-token introspection profile is approved.
13. Named operational ownership for provisioning, deprovisioning, tombstone registry durability/reconciliation, credential rotation, emergency revocation, backup/restore and disaster recovery.

Gate 1 role-mapping implementation must not pass without the cluster identity and independent tombstone durability design. Gate 4 endpoint retrieval implementation must not pass without the endpoint-resolution policy. Gate 5 and Gate 6 must not pass without the approved numerical execution/revocation profile and exact capacity/pooler profile. No gate passes by documentation alone; implementation and reproducible evidence remain mandatory.

### Updated consolidated disposition

| Finding | Severity | Disposition |
|---|---|---|
| IC-01-R2 | Medium | Cluster-scoped OID identity and independently recoverable tombstones specified; implementation proof required at Gate 1 |
| IC-03-R2 | High | Numerical execution/revocation values remain OPEN at Gate 0 |
| IC-04-R2 | Low | Endpoint-resolution and DNS/redirect restrictions specified; implementation tests required at Gate 4 |
| IC-05-R1 | High | Numerical capacity and exact pooler remain OPEN at Gate 0/Gate 5 |
| IC-06-R2 | Medium | Actual topology ADR remains OPEN at Gate 0 |

This revision does not select deployment values or topology on behalf of the deployment owner. It does not authorise merge, production deployment, customer-data processing, certification, live utility integration or SCADA/DMS operational activation.


## 17. Independent security re-review remediation — IC-01-R3 and IC-04-R3

**Review decision addressed:** APPROVED WITH CONDITIONS  
**Prior exact reviewed commit:** `8d22e33015f313614f8395fde63915156b1f8864`  
**Prior CI evidence:** workflow run #71, run ID `42859034512`, quality job ID `129979844975`  
**Scope:** specification and acceptance-test refinement only. No implementation, deployment or production approval is implied.

### IC-01-R3 — Tombstone authority separation and crash-safe lifecycle (Medium)

The authoritative retired-identity registry must have three logically and technically separate authority classes. These are required service/principal roles; each deployment must bind them to concrete workload identities, credentials and named human owners in its approved operational profile:

1. **Tombstone append authority — `powerops_tombstone_writer`:** a narrowly scoped deprovisioning service identity permitted to append a new retirement event and read back its committed receipt. It cannot reconcile catalog/mapping state, approve or execute exceptional removal, alter registry policy, or rewrite/delete existing events.
2. **Reconciliation authority — `powerops_tombstone_reconciler`:** a separate recovery/provisioning service identity permitted to read the authoritative registry and perform controlled catalog/mapping reconciliation. It cannot append retirement events on behalf of the writer, approve exceptional removal, or delete/modify historical events.
3. **Exceptional-removal approval and execution:** approval requires two distinct named security approvers, neither of whom may be the requesting operator or the writer/reconciler workload identity. Execution is performed by a separately controlled break-glass mechanism after both approvals; it cannot be performed by ordinary provisioning, migration, restore or runtime identities. The request, rationale, affected `(cluster_identity, role_oid)`, approvals, execution result and immutable audit reference must be retained. Exceptional removal is not a normal lifecycle operation.

The registry must enforce append-only event semantics. The deployment must document its concrete identity provider, authentication method, authorization boundary, credential custody/rotation, separation of duties, emergency access and named operational owners. The logical role names above are mandatory authority classes, not claims that corresponding cloud or database principals already exist.

#### Required deprovisioning protocol

Deprovisioning must be fail-closed across crashes and partial failures:

1. Create a unique, immutable retirement event identifier and append a durable retirement intent for `(cluster_identity, role_oid)` to the independent authoritative registry.
2. Wait for the registry's durable commit receipt. If append or receipt verification fails, do not report deprovisioning as complete; block new protected work for the affected identity/scope through the deployment's fail-closed control path.
3. Once the retirement intent is durably recorded, disable/revoke the database login and credentials, prevent new protected work, invalidate relevant application/pool credentials and terminate or drain affected sessions under the approved Gate 0 policy.
4. Reconcile the PostgreSQL catalog and active role-to-scope mapping against the authoritative retirement record. Remove/disable the active mapping and verify the role cannot authenticate or regain a scope.
5. Mark the event reconciled using a separate append-only completion event. Only then may the workflow report successful deprovisioning.

A crash at any step must be resumable by event ID. Retries must be idempotent: duplicate delivery of the same event ID returns the existing outcome and cannot create a second conflicting retirement identity. Conflicting events for the same cluster-scoped role identity must fail closed and raise an audited reconciliation incident. No retry may erase or supersede a retirement record.

The registry must have independently controlled backup and recovery, integrity verification (including authenticated integrity metadata), retention, access logging and restore testing. Its recovery point must not permit a PostgreSQL point-in-time restore to erase a later committed retirement event. Registry restore must verify event-chain/sequence integrity and reconcile against the cluster catalog and mappings before protected traffic is re-enabled. Registry unavailability, integrity failure, sequence gaps, stale recovery state or uncertain cluster identity disables protected identity resolution.

#### Mapping-key consistency

Clarify the Section 3 mapping model as follows:

- For a cluster-local mapping store, the PostgreSQL role OID is meaningful only within that one identified cluster; the mapping store must be cryptographically/configurationally bound to that cluster identity and must reject use against another cluster.
- For any centrally shared mapping or provisioning registry, the active identity key must be the composite `(cluster_identity, role_oid)`; role OID alone is never a globally unique key.
- The authoritative retirement registry always uses `(cluster_identity, role_oid)`, irrespective of whether active mappings are cluster-local or centrally stored.
- Provisioning must verify the target cluster identity and reject a retired composite key before creating or activating a role mapping.

#### Additional acceptance tests

- **C01-26:** prove only the configured writer workload can append retirement intents; runtime, migration, restore and reconciler identities cannot append.
- **C01-27:** prove reconciliation authority is distinct from writer authority and cannot approve or execute exceptional removal.
- **C01-28:** prove exceptional removal requires two distinct authorised security approvers and a separately controlled executor; self-approval and single-person approval fail.
- **C01-29:** inject a crash/failure after every deprovisioning persistence and revocation step; retries resume safely, no protected identity is reactivated, and the final state is reconciled.
- **C01-30:** replay duplicate event IDs and duplicate retirement deliveries; processing is idempotent and produces one authoritative retirement identity.
- **C01-31:** restore the independent registry from backup; verify integrity, sequence continuity, retention and recovery of all committed retirement events before reconciliation.
- **C01-32:** attempt unauthorised registry append, reconciliation, alteration, deletion and exceptional removal; each is denied and audited.
- **C01-33:** use identical numeric role OIDs in two clusters; central mappings and tombstones remain distinct by `cluster_identity`, and cluster-local stores reject cross-cluster use.
- **C01-34:** interrupt registry append before durable commit; deprovisioning is not reported complete and protected work fails closed for the affected identity.
- **C01-35:** simulate registry rollback, stale restore, integrity failure and sequence gap; protected identity resolution remains disabled.

### IC-04-R3 — DNS validation-to-connection binding (Medium)

Destination validation and socket connection must be one controlled operation. It is insufficient to validate a DNS answer and then allow the HTTP stack to resolve the hostname independently when opening the connection.

For every discovery and JWKS request:

- Resolve the configured, allowlisted hostname using the deployment's approved resolver policy and validate **every** returned A and AAAA address against the destination policy.
- Select only a validated address and bind the actual socket connection to that exact address. The HTTP client must not perform a second hostname resolution that can change the destination between validation and connection.
- Preserve normal TLS hostname verification, certificate validation and SNI for the configured hostname while connecting to the validated address. Do not replace hostname verification with IP-address certificate matching.
- If the HTTP library cannot safely bind a connection to the validated address while preserving hostname-based TLS verification, it must not be used for this trust-sensitive fetch path.
- Reject a DNS answer containing any prohibited address unless the deployment has an explicit, narrowly scoped approval for that exact destination. Apply policy to every address in CNAME resolution chains and to both IPv4 and IPv6.
- Disable automatic redirects by default. For any explicitly approved same-origin redirect, repeat resolution, destination validation and connection binding for the redirect target before connecting.
- Disable ambient proxy use by default. If an explicitly approved egress proxy is required, the proxy becomes part of the trusted network boundary and must enforce the same destination policy on the actual upstream connection; client-side validation alone is not sufficient.
- Connection pooling must not bypass current destination policy. Reuse is permitted only where the peer address is known, remains approved, and the connection's origin/trust binding is unchanged. On DNS/policy change, expiry, redirect, proxy-policy change or uncertainty, discard affected pooled connections and perform fresh validated resolution and connection binding.
- Record the configured hostname, resolved address set, selected peer address, TLS identity, redirect decision, policy version and fetch outcome in security audit evidence without logging secrets or token contents.
- Never accept discovery metadata or signing keys from a request whose actual connected peer cannot be proven to satisfy the approved destination policy.

#### Additional acceptance tests

- **C04-28:** change DNS between validation and socket creation; the client connects only to the exact validated address or fails closed.
- **C04-29:** provide mixed permitted and prohibited IPv4/IPv6 answers; prohibited answers cause rejection under the configured all-address policy.
- **C04-30:** use a CNAME chain whose terminal address is prohibited; request is rejected before metadata or keys are trusted.
- **C04-31:** redirect to an approved hostname that resolves to a prohibited address; the redirect is rejected before connection.
- **C04-32:** change DNS/policy after a connection is pooled; stale pooled connections are discarded and cannot bypass the new policy.
- **C04-33:** configure an ambient or malicious proxy that routes to a prohibited destination; fetch is rejected. An explicitly approved proxy must prove upstream destination enforcement.
- **C04-34:** verify the actual socket peer equals the selected validated address while TLS SNI, certificate chain and hostname verification remain bound to the configured hostname.
- **C04-35:** verify IPv4, IPv6, CNAME, redirect, connection reuse and DNS-rebinding cases against the actual HTTP client implementation, not mocks alone.
- **C04-36:** simulate resolver failure, inconsistent answers and policy-version changes during retrieval; no unvalidated discovery document or JWKS is accepted.

### Consolidated disposition and release boundary

| Finding | Severity | Contract disposition | Evidence still required |
|---|---|---|---|
| IC-01-R3 | Medium | Authority separation, lifecycle ordering, idempotency, recovery and mapping-key consistency specified | Implemented controls, crash/recovery tests and independent registry evidence |
| IC-04-R3 | Medium | Validated-address connection binding, TLS hostname preservation, proxy and pool controls specified | Actual HTTP-client/socket tests and independent endpoint-security evidence |
| IC-03-R2 | High | Gate 0 execution/revocation values remain OPEN | Deployment-owner-approved numerical profile |
| IC-05-R1 | High | Gate 0 capacity and exact pooler remain OPEN | Approved capacity profile and exact pooler/version/mode |
| IC-06-R2 | Medium | Topology ADR remains OPEN | Approved topology decision record |

This section does not close the findings by documentation alone. It does not select deployment-specific principals, numerical limits, pooler, provider or topology without deployment-owner approval. All affected implementation gates remain blocked until their prerequisites, implementation and reproducible evidence are independently verified. No production deployment, customer-data processing, certification, live utility integration or SCADA/DMS operational activation is authorised.


## 18. Independent security re-review remediation — IC-01-R4 and IC-04-R4

**Review decision addressed:** APPROVED WITH CONDITIONS  
**Prior exact reviewed commit:** `1991f2c0f17ee218a406481c08e8ff2066b1eb5e`  
**Scope:** additional contract and acceptance-test requirements only. This section does not claim implementation evidence or close deployment-owner decisions.

### IC-01-R4 — Cryptographically bound exceptional removal and retirement-intent fencing (Medium)

#### Exceptional-removal request and approval protocol

An exceptional-removal request must be represented by a canonical, immutable request object. Its digest must cover at least:

- A unique request ID and nonce.
- The exact stable `cluster_identity` and `role_oid`.
- The requested action (exceptional tombstone removal), reason code and complete human-readable rationale.
- The initiating operator's stable identity-provider subject.
- Creation time, expiry time and the applicable policy/version identifier.
- The relevant tombstone event ID(s) and registry sequence/version.
- The target environment and deployment identity.

The canonical serialization and digest algorithm must be fixed by the deployment security profile. Approval records must be cryptographically authenticated by the approved identity/signing mechanism and bind to the exact request digest; approvals for a different cluster, role, event, reason, environment, policy version or request digest are invalid.

The two approvers must be independently authenticated human identities. Distinct usernames, accounts, email aliases or credentials alone are insufficient evidence of distinct people. The deployment must enforce distinct immutable workforce/identity-provider subject identifiers and an authoritative person-uniqueness control. Where the identity provider cannot establish distinct underlying people, exceptional removal is prohibited until an independently controlled identity-proofing process is approved.

Each approval must include the approver's stable subject, authenticated assurance context, request digest, approval decision, timestamp, expiry, unique approval ID and cryptographic verification material/reference. Approvals must be time-limited, single-use and protected against replay. The executor must independently retrieve and verify both approvals, verify that the approvers are distinct from each other and the requester, verify authorisation and expiry, verify the exact request digest and current tombstone state, and verify that neither approval has previously been consumed. The executor must fail closed on any missing, invalid, revoked, expired, duplicated or unverifiable approval.

The executor must not trust a caller-supplied assertion that approval has occurred. Approval verification and one-time consumption must be atomic with recording the execution attempt, using a strongly consistent authoritative approval ledger. If atomic consumption cannot be guaranteed, exceptional removal is disabled.

Append immutable audit events for request creation, each approval attempt, rejection, expiry, replay detection, verification failure, execution attempt, success and failure. Audit records must retain request digest, stable actor subjects, decision, timestamps, policy version and correlation IDs, but must not expose secrets or signing material. Failed and rejected attempts are retained under the same tamper-resistant audit controls as successful actions.

#### Retirement-intent fencing

A durable retirement intent is an immediate security fence, not merely a workflow notification. From the point the authoritative registry commits the intent, no new protected work may begin for the retired `(cluster_identity, role_oid)`, even while database credential revocation, pool eviction, mapping reconciliation or session termination is pending.

The authorization path must consult a strongly consistent retirement-fence authority before granting each new protected unit of work, or use an equivalent cryptographically verifiable fencing-token design that guarantees a stale positive mapping/cache cannot authorise work after the durable intent. A bounded positive mapping cache alone is not sufficient to meet the immediate-fence requirement.

Requirements:

- The retirement intent must atomically advance or create a monotonic fence generation for the composite identity key.
- Every protected-work admission must validate the current active state and fence generation against an authoritative, strongly consistent source. Any cached permit must be bound to a fence generation and must not remain usable after a newer retirement generation commits.
- The writer must not report durable intent until both the retirement event and the corresponding fence are committed and independently readable.
- If the fence authority is unavailable, stale, inconsistent or cannot prove the current generation, new protected work is denied.
- Existing sessions and already-admitted work are handled under the approved IC-03 Gate 0 cancellation/in-flight-write policy; no new work may enter while that handling proceeds.
- Fence clearing or identity reactivation is prohibited through ordinary provisioning. Any exceptional recovery requires a separate reviewed, dual-controlled procedure and a new identity lifecycle event; a prior tombstone must never be silently erased.
- The audit trail must correlate retirement intent, fence generation, rejected admissions, credential revocation, session actions, mapping reconciliation and completion.

#### Additional acceptance tests

- **C01-36:** mutate each security-relevant request field after approval; request digest mismatch prevents execution.
- **C01-37:** submit approvals for another cluster, role OID, tombstone event, environment, reason or policy version; executor rejects each.
- **C01-38:** replay an approval, reuse an approval ID, submit an expired/revoked approval or race two executions; exactly one valid consumption is possible.
- **C01-39:** use two accounts/aliases mapped to the same underlying person; distinct-person control rejects the pair.
- **C01-40:** use two independently authenticated, authorised human subjects; verify executor independently validates both signatures, identity uniqueness, expiry, request digest and one-time status.
- **C01-41:** inject failures during approval verification and atomic consumption; no removal occurs and all attempts are immutably audited.
- **C01-42:** crash immediately after durable retirement intent/fence commit and before database revoke; after restart, new protected work remains denied and reconciliation resumes by event ID.
- **C01-43:** issue concurrent protected requests immediately before, during and after retirement-intent commit; no request admitted after the authoritative fence commit may begin protected work.
- **C01-44:** retain a stale positive mapping cache or previously issued admission permit across retirement; fence-generation validation rejects it.
- **C01-45:** make the fence authority unavailable, stale or inconsistent; new protected work fails closed.
- **C01-46:** restore the registry from a validly signed but incomplete event sequence; integrity/sequence verification fails and protected work remains disabled.
- **C01-47:** retry after database role revocation but before completion-event append; reconciliation is idempotent and cannot reactivate the identity.
- **C01-48:** restore a cluster with changed or duplicated cluster identity; traffic remains disabled until independently authorised identity reconciliation completes.

### IC-04-R4 — DNS freshness, connection lifetime and pooled-connection invalidation (Medium)

#### DNS freshness and connection reuse policy

Each deployment must publish explicit numeric DNS and connection-lifetime parameters in its endpoint-security profile. A resolver answer may be cached only until the earliest of its DNS TTL expiry and the deployment's configured maximum DNS cache age. The profile must define a finite maximum DNS cache age; an absent, zero/invalid or unbounded value is a configuration error and fails closed.

Before opening a new connection after DNS cache expiry, the client must resolve again and repeat full A/AAAA/CNAME destination validation. DNS freshness is not extended by connection reuse. Every connection must have a finite maximum age, no greater than the deployment-approved maximum connection reuse lifetime. The implementation must enforce both idle timeout and absolute connection age; activity must not extend the absolute maximum age.

Each pooled connection must be bound to a key containing at least the configured origin (scheme, hostname and port), selected peer IP, TLS server identity, trust/configuration version and destination-policy version. A connection is reusable only while all bindings remain current and approved.

A destination-policy version change must synchronously invalidate affected pooled connections before any subsequent request is admitted. A DNS refresh that changes the validated address set, a newly prohibited peer, a trust-anchor/TLS policy change, redirect-policy change or proxy-policy change must invalidate affected connections and prevent further use of prohibited peers. Where immediate invalidation cannot be guaranteed, the fetch path must stop and fail closed rather than reuse uncertain connections.

HTTP/2 connection coalescing across hostnames must be disabled for discovery/JWKS traffic unless a separately reviewed design proves that each coalesced origin independently satisfies DNS, peer, TLS, origin and policy binding. HTTP/2 multiplexed streams must not allow a request admitted under an older policy version to bypass a newer policy. The default implementation is one origin per connection, no cross-origin coalescing, and no reuse after policy-version change.

For explicitly approved proxies, the deployment profile must identify the proxy product/version and require authenticated, tamper-resistant upstream-destination evidence. That evidence must identify the actual upstream peer IP, requested hostname, TLS identity where applicable, policy version and decision, and be independently retrievable for audit. A proxy's own address or an unverified assertion is not proof of upstream destination enforcement. If this evidence is unavailable or cannot be correlated to the fetch, the proxy path is not approved.

The numeric DNS cache-age, maximum connection age, idle timeout, policy propagation/invalidation bound and any proxy evidence-retention values are deployment Gate 0/profile decisions; they must be explicitly set and approved before endpoint retrieval is enabled. The implementation must reject missing or out-of-range values rather than silently applying library defaults.

#### Additional acceptance tests

- **C04-37:** DNS answer TTL shorter/longer than configured maximum; effective cache age is the lesser bound and expired answers are not reused.
- **C04-38:** DNS cache expires while requests are concurrent; each new connection uses a freshly validated address and cannot race a second resolution.
- **C04-39:** policy version changes while HTTP/1.1 keep-alive and HTTP/2 connections are pooled; affected connections are invalidated before another request.
- **C04-40:** an existing peer becomes prohibited; no new stream/request uses that connection, and active connections are closed or fetch service fails closed within the approved policy bound.
- **C04-41:** attempt HTTP/2 connection coalescing across two hostnames with different DNS/policy outcomes; default client rejects coalescing.
- **C04-42:** test HTTP/2 multiplexing during policy-version change; no request proceeds under stale policy.
- **C04-43:** test maximum absolute connection age and idle timeout under continuous traffic; activity cannot extend the absolute lifetime.
- **C04-44:** change A/AAAA answers and CNAME chains during concurrent validation/connection attempts; actual socket peer always matches a currently validated address or request fails closed.
- **C04-45:** use proxy environment variables, operating-system proxy settings and application-level proxy configuration; none can bypass the configured proxy policy.
- **C04-46:** approved proxy provides no verifiable upstream destination evidence, mismatched evidence or evidence for another request; fetch is rejected and audited.
- **C04-47:** verify TLS rejects a certificate valid for a different hostname even when the socket connects to the correct validated IP.
- **C04-48:** change DNS, TLS trust, destination policy and proxy policy independently; each relevant change invalidates all affected pooled connections before reuse.
- **C04-49:** omit or misconfigure DNS cache age, maximum connection age or policy invalidation bound; endpoint retrieval remains disabled.
- **C04-50:** run all DNS, socket, TLS, proxy and pool-reuse tests against the exact selected production HTTP client/version and transport configuration; mocks alone cannot pass the gate.

### Gate 0 decision register — no silent defaults

The following decisions remain explicitly OPEN and must be completed in a deployment-owner-approved, version-controlled profile before the dependent gates pass:

| Decision group | Required approved values/evidence | Dependent gate |
|---|---|---|
| IC-03-R2 execution/revocation | Maximum transaction, query and job durations; new-work revocation propagation; query cancellation; session termination; positive membership-cache lifetime; in-flight write rollback/completion policy | Gates 1, 5 and 6 as applicable |
| IC-05-R1 capacity/pooler | Tenant, BU, scope and concurrent-connection targets; per-scope pool min/max; global connection budget; provisioning/rotation throughput; exact PostgreSQL and pooler product/version/configuration/mode; measured `session_user` preservation | Gates 1 and 5 |
| IC-06-R2 topology | Approved ADR selecting shared DB with scope-bound roles, separate DBs in one cluster, or separate clusters/instances; trust boundaries, operations, backup/restore, DR and cross-tenant controls | Gates 0, 1 and 6 |
| IC-04-R4 endpoint freshness | Maximum DNS cache age, maximum absolute connection age, idle timeout, policy invalidation bound, selected HTTP client/version, HTTP/2/coalescing policy and any proxy evidence requirements | Gate 4 |
| IC-01-R4 approval/fencing | Approved identity provider and stable human subject uniqueness source; signature/key custody and rotation; approval lifetime; replay ledger; strongly consistent fence authority and failure behaviour; named operational owners | Gate 1 |

No numeric values in this table may be inferred from library defaults or selected by implementation engineers without deployment-owner approval. Engineering may implement configurable, fail-closed mechanisms and test harnesses before the deployment profile is final, but the affected release gates cannot pass until the actual profile is approved and tested.

### Updated disposition

| Finding | Severity | Contract disposition | Evidence still required |
|---|---|---|---|
| IC-01-R3 | Medium | Addressed at contract level | Implementation, crash recovery and registry evidence |
| IC-01-R4 | Medium | Requirements and tests specified | Cryptographic approval, distinct-person enforcement and concurrent fencing tests |
| IC-04-R3 | Medium | Addressed at contract level | Actual HTTP-client/socket evidence |
| IC-04-R4 | Medium | DNS freshness, pooling and invalidation requirements specified | Exact client/version tests and approved numeric endpoint profile |
| IC-03-R2 | High | OPEN — deployment-owner decision | Approved numerical execution/revocation profile |
| IC-05-R1 | High | OPEN — deployment-owner decision | Approved capacity and exact pooler profile |
| IC-06-R2 | Medium | OPEN — deployment-owner decision | Approved topology ADR |

**Release boundary:** This section is a specification and test-plan change only. It does not claim the new controls are implemented or tested, does not close Gate 0, and does not authorise merge, deployment, production data, certification, live utility integration or SCADA/DMS operational activation.


## 19. Initial deployment architecture recommendation and Gate 0 profile

**Status:** proposed reference architecture; deployment-owner approval required  
**Purpose:** establish one consistent initial deployment model without inventing customer capacity, operational limits, identity-provider details or service-level objectives.

### 19.1 Initial deployment model

The recommended initial commercial and security model is **one customer-controlled PowerOps deployment per utility customer**. The initial release is not a shared multi-customer SaaS runtime.

For the high-assurance reference topology, the recommended default is:

- One dedicated customer-controlled production deployment per utility customer.
- A separate PostgreSQL cluster or independently administered PostgreSQL instance for that customer, rather than multiple customers sharing one PostgreSQL cluster.
- Separate staging/test and production environments, credentials, signing keys, trust configuration, audit stores and network policy.
- Customer-controlled network boundaries, backup custody, recovery operations and access approval.
- Within each customer deployment, preserve mandatory tenant and business-unit isolation. Use a distinct authenticated database scope for every tenant/BU scope; do not infer tenant-wide access from absent BU context.
- Do not use a shared cross-customer runtime database login, shared writable scope variable, or schema-only separation as a substitute for the authenticated database boundary.
- Customer-specific identity provider, OIDC issuer/audience profile, key custody, endpoint allowlist and approved egress path.
- PowerOps remains advisory-only. No dispatch, switching, protection-setting, SCADA/DMS command or other operational control path is in scope.

**Rationale:** this topology aligns with customer-controlled deployment and data custody, reduces cross-customer blast radius, and makes backup/restore, incident response and customer-specific identity/egress policy independently governable. It has higher infrastructure and operational cost than a shared cluster; that cost must be assessed against the actual customer deployment.

**Important:** this is an engineering recommendation, not a completed IC-06 decision. The deployment owner must approve or reject it in a signed/version-controlled ADR. If rejected, the ADR must compare all three alternatives in Section 8 and document residual risks and compensating controls.

### 19.2 Topology decision record (ADR-PWR-001)

| Field | Proposed decision / required evidence | Status |
|---|---|---|
| Commercial deployment boundary | One customer-controlled deployment per utility customer | Recommended; owner approval pending |
| Initial customer tenancy | No cross-customer shared runtime | Recommended; owner approval pending |
| PostgreSQL boundary | Dedicated cluster or independently administered instance per customer | Recommended; owner approval pending |
| Tenant/BU isolation inside customer boundary | Authenticated scope-bound database identities plus RLS and composite constraints | Mandatory contract invariant |
| Staging/production separation | Separate environments and credentials; no shared signing secrets | Required; implementation evidence pending |
| Database topology alternatives | Compare shared DB/RLS, separate DBs within one cluster, and separate clusters/instances | ADR approval pending |
| Backup/restore and DR | Customer-controlled, tested, tenant-safe restore and recovery; named operators | Owner and evidence pending |
| Pooler | Exact product/version/mode selected only after session_user conformance test | OPEN |
| PostgreSQL version | Explicitly selected and supported version | OPEN |
| Capacity and performance | Derived from approved workload model and load test; no assumed scale | OPEN |
| Operational authority | Named customer and CEPHAS owners for provisioning, revocation, tombstones, keys, backup, incident response | OPEN |

### 19.3 Capacity model — values must come from workload evidence

Do not choose a tenant count, BU count, role count, pool size or connection budget by guesswork. For each pilot customer, record:

- Number of legal tenants and business units, including explicit tenant-wide scopes.
- Maximum simultaneously active scopes.
- Peak concurrent authenticated users, API requests, protected transactions and background jobs.
- Peak connection demand by scope and aggregate connection budget.
- Provisioning, deprovisioning and credential-rotation events per hour/day.
- Expected data volume, audit-event rate, retention and backup growth.
- Availability, recovery-time and recovery-point objectives.
- Expected utility network latency, outage duration and disconnected operation requirements.
- Peak-load test profile, safety margin, measured resource consumption and tested failure behaviour.

Calculate and test pool budgets against the selected PostgreSQL and pooler limits, including administrative, migration, monitoring, backup and emergency reserve connections. The sum of all per-scope pools must never exceed the approved global database connection budget. Pool exhaustion must cause bounded backpressure; it must never trigger a shared-login or cross-scope fallback.

### 19.4 Gate 0 parameter approval and evidence matrix

The companion file `docs/POWEROPS_0.1.1_DEPLOYMENT_PROFILE.template.yaml` is the required version-controlled profile template. Every `null`, `TBD` or `UNAPPROVED` field is a release blocker for its dependent gate. The deployment owner must approve exact values and evidence; engineering may not fill them with arbitrary defaults.

| Gate 0 group | Required decision/evidence | Required approver |
|---|---|---|
| IC-03-R2 execution/revocation | Numeric transaction/query/job maxima; new-work revocation propagation; positive membership-cache bound; query/session/job cancellation deadlines; in-flight write rollback/completion rule; outage behaviour | Customer security owner and PowerOps service owner |
| IC-05-R1 capacity/pooler | Workload/capacity model; per-scope pool min/max; global connection budget/reserve; churn/rotation rates; exact PostgreSQL and pooler product/version/mode; measured `session_user` preservation | Customer DBA/platform owner and PowerOps engineering owner |
| IC-06-R2 topology | Approved ADR-PWR-001; selected topology; threat model; operations, backup/restore, DR, migration and cost evidence | Customer architecture/security authority |
| IC-04-R4 endpoint | Exact HTTP client/version; DNS cache age; absolute connection age; idle timeout; policy invalidation bound; proxy product/version/evidence retention if applicable; destination policy | Customer network/security owner |
| IC-01-R4 identity/fencing | OIDC issuer/provider profile; immutable human identity uniqueness source; signing algorithm/key custody/rotation/revocation; approval lifetime; replay ledger; fence authority consistency and outage behaviour; named operational owners | Customer IAM/security owner |
| Operational resilience | RTO/RPO; backup custody; restore test; cluster identity and tombstone recovery; incident response and emergency access | Customer operations/security owner |

### 19.5 Implementation sequencing and stop conditions

1. Approve ADR-PWR-001 and the deployment profile before finalising topology-dependent implementation.
2. Build provider-neutral OIDC adapter/conformance harness and test harnesses only where their contracts are stable; do not enable an unapproved provider.
3. Implement authenticated scope identity, mapping, RLS and SECURITY DEFINER hardening against the approved PostgreSQL version/topology.
4. Implement revocation, retirement fencing, tombstone registry and recovery against the approved consistency and timing profile.
5. Implement the selected pooler and prove `session_user` preservation under normal, failure, restart and credential-rotation conditions.
6. Implement JWKS endpoint retrieval using the selected HTTP client and approved endpoint profile; prove actual socket peer, TLS identity, DNS freshness, redirects, proxies and pool invalidation.
7. Run the full PostgreSQL adversarial, identity, revocation, crash/recovery, endpoint and capacity suite against production-equivalent components.
8. Obtain independent security and qualified power-systems reviews before any consideration of deployment or integration.

A gate cannot pass because its value is documented alone: the value must be approved by the named owner and supported by reproducible tests/evidence. Any unapproved, missing, stale or out-of-range value fails closed. No pilot or production activation is authorised by this planning document.

### 19.6 Consolidated closure status

- **IC-01-R3:** contract requirements specified; implementation and recovery evidence outstanding.
- **IC-01-R4:** contract requirements specified; identity uniqueness, approval executor and fencing implementation/evidence outstanding.
- **IC-01-R5 through R7:** Section 20 specifies atomic admission/fence ordering, cluster identity lifecycle, and requester/approver/executor separation; implementation and concurrency/recovery evidence outstanding.
- **IC-03-R3:** Section 20 classifies the 30-second membership-cache ceiling and 60-second clock-skew baseline; deployment-specific clock configuration and synchronisation evidence outstanding.
- **IC-05-R2:** Section 20 adds explicit database role and credential ceilings to the profile; owner values and load/provisioning evidence outstanding.
- **IC-06-R3:** Section 20 aligns the three topology alternatives across the contract and ADR; signed ADR outstanding.
- **IC-07-R2:** Section 20 defines the consolidated evidence manifest and profile references; reproducible runtime bundle outstanding.
- **IC-03-R2:** OPEN pending approved numeric execution/revocation profile and runtime proof.
- **IC-04-R3:** contract requirements specified; actual HTTP-client/socket evidence outstanding.
- **IC-04-R4:** contract requirements specified; approved endpoint profile and actual-client evidence outstanding.
- **IC-05-R1:** OPEN pending approved capacity and exact pooler profile, plus measured conformance.
- **IC-06-R2:** OPEN pending signed ADR-PWR-001 and topology/recovery evidence.
- **IC-07:** OPEN pending reproducible PostgreSQL adversarial evidence bundle.

**Release boundary:** Section 19 is an architecture recommendation and decision framework. It does not claim owner approval, select unknown numerical values, close Gate 0, authorise merge, or authorise deployment, production data, live utility connectivity, SCADA/DMS integration or operational control.


## 20. Consolidated independent re-review remediation — IC-01-R5 through IC-07-R2

**Review basis:** independent security re-review of exact commit `4705daefe285fcc9352a59110807804b2d3c9e60`.  
**Purpose:** close specification gaps identified in that review. This section changes contract requirements and acceptance tests only; it does not claim implementation, Gate 0 approval or runtime evidence.

### 20.1 IC-01-R5 — Atomic protected-work admission relative to retirement fencing (High)

A point-in-time fence check followed by an independently delayed operation is insufficient. A request must not pass an admission check, pause, and begin protected work after the retirement fence has committed.

**Required linearization semantics**

1. Define the authoritative retirement-fence record for each `(cluster_identity, role_oid)` with a monotonic generation and lifecycle state. The admission authority and protected database transaction must share a linearizable/transactional enforcement point, or use a resource-enforced fencing-token protocol with equivalent guarantees.
2. For PostgreSQL-protected work, the admission path must acquire a transaction-scoped lock on the authoritative identity/fence row, verify the identity is active and the supplied generation is current, and begin the protected database unit of work while that lock is held. The lock must remain held through the protected transaction's commit or rollback. The fence writer must acquire the conflicting lock, persist the retirement intent and increment the generation in the same transaction, then commit.
3. This establishes a single ordering: a protected transaction that acquires the lock first is already admitted and is governed by the approved IC-03 in-flight-work policy; a retirement transaction that commits first causes every later admission to observe the retired state/new generation and reject. A permit or token issued before work begins is not, by itself, admission and must not be usable to start work later.
4. A queued background job is not admitted merely because it was enqueued or assigned a permit. The worker must acquire the current fence at actual execution start and establish the protected transaction under the same ordering. Queue state must not bypass the fence.
5. For any non-database protected resource, the resource itself must atomically validate and enforce the monotonic fencing generation at the point of the protected effect. If the resource cannot enforce the generation, that operation is not eligible for this contract. No delayed bearer permit may authorise an effect after a newer retirement generation commits.
6. Retirement intent and generation advancement must commit before the writer acknowledges the durable fence. The retirement writer must not bypass or invalidate an in-progress protected transaction; it waits for the admission lock and then commits the fence. Conversely, after that commit, no later protected transaction may acquire admission.
7. Define lock ordering, transaction isolation, timeout/deadlock handling and failure behavior for the selected database/version. Any uncertain lock, stale generation, authority outage or inability to prove ordering fails closed. No admission based only on a cache, asynchronously replicated read, or eventually consistent status.
8. This ordering governs new work. Handling of transactions admitted before the fence commit remains controlled by the approved IC-03 policy; this section does not silently choose rollback or bounded completion.

**Additional deterministic acceptance tests**

- **C01-49:** pause a request after it begins admission but before its first protected SQL statement; race retirement. Verify lock ordering means either the protected transaction is already admitted and retirement waits, or retirement commits first and the request is denied. No protected SQL may begin after a committed retirement fence.
- **C01-50:** hold a protected transaction open while retirement attempts to commit; verify retirement cannot commit its fence ahead of the admitted transaction's lock, and new admissions queue/reject according to policy.
- **C01-51:** commit retirement first, then release a previously issued but not yet used admission permit; verify the permit cannot start work.
- **C01-52:** enqueue a job before retirement, pause the worker, commit retirement, then resume the worker; execution is rejected at actual start.
- **C01-53:** test concurrent admission and retirement repeatedly under the exact PostgreSQL isolation/locking configuration; assert transaction order and persisted rows, not only API responses.
- **C01-54:** inject lock timeout, deadlock, database failover, authority outage and ambiguous commit outcomes; uncertain admission/fence state fails closed and reconciliation is idempotent.
- **C01-55:** for any non-database protected resource, submit a stale fencing generation after a newer generation commits; the resource rejects the operation. If no resource-side enforcement exists, the integration test must prove the operation is disabled.

### 20.2 IC-01-R6 — Stable cluster identity and tombstone-registry lifecycle (Medium)

The deployment profile must define:

- The authoritative source/issuer and format of `cluster_identity`, the provisioning authority, uniqueness assurance and custody of its registration.
- How the identity is persisted independently of mutable hostname, IP address, DNS name, filesystem clone or PostgreSQL role OID.
- How a new cluster, cloned image, point-in-time restore, standby promotion and disaster-recovery restore obtain or retain a cluster identity.
- A clone must never become active with a duplicated identity. It remains isolated from protected traffic until a unique identity is issued or an explicitly authorised original-identity recovery is completed.
- A restored replacement may retain the original identity only after the former instance is demonstrably fenced from service and split-brain/duplicate-active operation is prevented. Otherwise it receives a new identity and undergoes controlled mapping/tombstone reconciliation.
- The tombstone registry's authoritative identity/product or service, owner, writer, consistency/commit semantics, sequence authority, stated recovery-point objective (RPO), append-only/integrity controls, independent backup and restore process.
- The recovery procedure for registry loss, rollback, incomplete event sequence, duplicate cluster identity and disagreement between registry and PostgreSQL catalog. Conflicts disable protected work pending authorised reconciliation.
- Registry authority and mapping-store mode must be explicit: `cluster_local` or `central`. The registry key is always composite `(cluster_identity, role_oid)`. A cluster-local mapping store may use `role_oid` only when its containing cluster identity is cryptographically/administratively bound and verified at runtime. A central mapping store must use the composite key and verify the cluster identity on every lookup; it must not infer cluster identity from a caller-supplied value.

**Additional acceptance tests**

- **C01-56:** provision two clusters from the same image; verify they cannot both activate with one identity.
- **C01-57:** restore a backup while the original cluster is still reachable; verify the restored instance remains isolated until the original is fenced or a new identity is assigned.
- **C01-58:** change hostname/IP/DNS while retaining the same authorised cluster lifecycle; verify identity remains stable and is not inferred from network naming.
- **C01-59:** simulate a cloned/stale registry or PostgreSQL catalog with a conflicting identity/role mapping; protected work remains disabled pending reconciliation.
- **C01-60:** restore the tombstone registry from backup and verify sequence continuity, integrity, event completeness and reconciliation against the actual PostgreSQL catalog.

### 20.3 IC-01-R7 — Exceptional-removal actor separation and approval configuration (Medium)

Extend the exceptional-removal protocol so that:

- The requester, each of the two approvers, and the execution workload identity are four distinct principals/roles. The executor is a dedicated non-human workload identity and cannot be the requester or either approver.
- The two approvers are distinct verified natural persons, not merely distinct accounts. Both are independently authorised for the exact target environment and action.
- The canonical approval digest covers a versioned canonicalisation scheme, digest algorithm, request ID/nonce, cluster identity, role OID, tombstone event/sequence, reason, requester, target environment, policy version, creation/expiry, and action. Any field change invalidates both approvals.
- The deployment profile must define the approval trust/verification profile, permitted signature algorithms and key types, approver authentication assurance level, authoritative human identity proofing, key custody/rotation/revocation and verifier policy. A valid signature under an unapproved algorithm/key or an approval below the required authentication assurance is rejected.
- Approval verification and one-time consumption are atomic in the approved strongly consistent ledger. The deployment profile must identify the concrete transaction/atomic-commit mechanism (for example, a single serializable database transaction or an equivalent compare-and-consume primitive), its uniqueness/idempotency constraint, durability and failover semantics. The ledger's product/authority, consistency model, durability, backup/recovery, retention, replay handling and audit evidence are deployment-profile decisions.
- The executor re-fetches the canonical request and both approval records from the authoritative ledger, independently verifies signatures, identities, distinct-person status, role separation, expiry, revocation, policy and current tombstone state, and atomically consumes the approvals before execution.
- Any unavailable identity source, ambiguous human identity, ledger inconsistency, executor credential compromise or audit failure disables exceptional removal. No manual database edit or direct tombstone deletion is an alternate path.

**Additional acceptance tests**

- **C01-61:** requester attempts to act as either approver; reject.
- **C01-62:** executor identity matches requester or either approver; reject and disable execution.
- **C01-63:** approver identities are distinct accounts but resolve to the same person; reject.
- **C01-64:** change canonicalisation version, digest algorithm or any bound field; both approvals become invalid.
- **C01-65:** interrupt ledger consumption/executor execution at every transaction boundary; no partial approval consumption can authorise a second execution.
- **C01-66:** restore or fail over the approval ledger; replay protection and one-time consumption remain consistent, otherwise exceptional removal remains disabled.
- **C01-67:** rotate an approval signing key; only the configured overlap/active key policy is accepted and retired keys cannot authorise new approvals.
- **C01-68:** revoke a signing key while approvals are pending; executor rejects approvals signed by the revoked key according to the approved revocation policy.
- **C01-69:** submit an unapproved signature algorithm, key type or key; verification rejects it.
- **C01-70:** submit an approval with authentication assurance below the configured minimum; executor rejects it.
- **C01-71:** race two executions against the same pair of approvals; the ledger permits exactly one atomic consumption and one execution.

### 20.4 IC-03-R3 — Numeric ceiling and clock-skew classification (Medium)

The numeric values already present in the contract are classified as follows:

- **Positive membership-cache lifetime:** 30 seconds is a contract-wide hard maximum for a positive membership cache used to admit new protected work. This bounds the exposure window from stale positive membership data; it does not replace the immediate retirement-fence protocol or terminate already-admitted work. A deployment may choose a lower value, and the runtime/profile validator must enforce that lower approved value. A value above 30 seconds is prohibited under this contract and is not an ordinary deployment exception.
- **JWT clock skew:** 60 seconds is a provisional baseline default, not a deployment approval and not a universal hard ceiling. It is a compatibility starting point for bounded clock differences, not permission to tolerate unsynchronised hosts. The deployment profile must set the actual maximum. A value above 60 seconds requires a documented exception, evidence that the identity provider and hosts maintain reliable time, and independent security approval before enablement.
- **Clock synchronisation:** each deployment must identify its trusted time source/service, synchronisation method, monitoring and drift alerting. Hosts validating tokens, issuing approvals, writing tombstones and consuming replay-ledger entries must use monitored time. Clock synchronisation loss, unbounded drift or inability to determine trustworthy time fails closed for token acceptance and time-bound exceptional approvals.
- All other transaction/query/job, revocation, cancellation and termination values remain deployment-owner decisions. No additional numeric defaults are introduced here.

**Additional acceptance tests**

- **C03-10:** attempt to configure positive membership-cache lifetime above 30 seconds; configuration validation rejects it.
- **C03-11:** configure a value below 30 seconds; runtime enforces the stricter approved value under measured revocation tests.
- **C03-12:** omit the deployment's JWT clock-skew value or time-synchronisation source; token validation/approval operations remain disabled.
- **C03-13:** simulate clock drift, time-source outage and disagreement between nodes; expired/not-yet-valid tokens and time-bound approvals fail closed according to the profile.
- **C03-14:** configure clock skew above 60 seconds without an approved exception record; profile validation rejects it.

### 20.5 IC-05-R2 — Explicit role and credential capacity ceiling (Medium)

The capacity profile must contain separate owner-approved maxima for:

- PostgreSQL login roles, including active, staged and reserved provisioning roles.
- Active credentials and concurrently valid credential versions during rotation.
- Retired role identities/tombstones retained for audit and replay prevention.
- Total cluster-wide roles, including application, migration, monitoring, backup, pooler and emergency administration roles.

The workload model must show how the maximum is calculated, how role/credential headroom is reserved, how rotation overlap is bounded, and what happens at exhaustion. Provisioning must stop with an auditable, fail-closed error before any configured ceiling is exceeded. It must not delete tombstones, recycle an identity, or switch to shared credentials to recover capacity.

**Additional acceptance tests**

- **C05-10:** provision roles/credentials to the approved maximum; the next request is rejected before exceeding it.
- **C05-11:** perform credential rotation at maximum capacity; overlap is bounded by the approved profile and old credentials are revoked.
- **C05-12:** exhaust role/credential headroom during tenant/BU provisioning; no partial identity is activated and no tombstone is removed.
- **C05-13:** restore role catalog and tombstone registry; counts reconcile without reusing retired role identities.

### 20.6 IC-06-R3 — Consistent three-option topology decision (Low)

Sections 8, 19 and the deployment profile must use the same three alternatives:

1. Shared database with scope-bound login roles and RLS.
2. Separate databases within one PostgreSQL cluster. Roles remain cluster-wide; database separation alone does not create separate role namespaces or separate cluster-administration boundaries.
3. Separate PostgreSQL clusters or independently administered instances, with distinct cluster-level role namespaces and administration/recovery boundaries.

ADR-PWR-001 must compare all three using the same criteria: authenticated trust boundary, tenant/BU isolation, credential/role scope, network and administrative separation, failure/blast radius, migration, backup/restore, DR, monitoring, connection/pool limits, cross-tenant analytics, operating cost and residual risk. The chosen option and rejected alternatives require named owner approval. The reference recommendation in Section 19 remains a recommendation until signed; it must not be described as an approved topology.

**Additional acceptance tests**

- **C06-07:** validate the ADR and profile enumerate exactly these three alternatives and distinguish cluster-wide roles from database-local objects.
- **C06-08:** for the selected option, test cross-tenant authentication and access using actual tenant credentials and production-equivalent PostgreSQL privileges.
- **C06-09:** verify the signed ADR, selected option, profile value and deployed topology are identical; any mismatch blocks the gate.

### 20.7 IC-07-R2 — Consolidated evidence-bundle traceability (Medium)

Every implementation gate must produce one versioned, tamper-evident evidence bundle with a manifest that identifies the exact source and runtime under test. The deployment profile must reference the bundle URI, manifest, integrity/signature record and independent reviewer report.

At minimum the bundle must include:

1. Exact source commit, PR, workflow/run/job IDs, test command, test result and timestamp.
2. Environment/deployment identity, cluster identity, PostgreSQL product/version/build, relevant server configuration and configuration digest.
3. Migration IDs, ordered migration history, checksums and resulting schema version.
4. Role/credential inventory (redacted identifiers only), memberships, effective privileges, ownership, RLS enabled/forced status and policy inventory.
5. SECURITY DEFINER function definitions, owner attributes, effective grants, search_path and object-privilege evidence.
6. Actual `session_user`, `current_user`, cluster identity and composite mapping resolution captured from the database during tests.
7. Executed adversarial SQL/scripts, test source revision, complete logs, exit status and machine-readable results.
8. Before/after persisted-state assertions for successful, rejected, cancelled, rolled-back and recovery scenarios; include relevant row counts or redacted record identifiers and transaction ordering.
9. Pooler and HTTP-client exact product/version/configuration, actual socket peer/TLS evidence, DNS and connection-policy observations where those gates apply.
10. Backup/restore, failover, tombstone-registry and approval-ledger recovery evidence where those gates apply.
11. Artifact hashes, evidence-generation procedure, storage location/access controls, retention, signing/attestation identity and chain-of-custody metadata.
12. Known limitations, skipped tests (with reason and gate impact), deviations, residual findings and independent reviewer decision.

A screenshot, summary table, mocked test, lint/type-check result or CI green badge alone is not a runtime evidence bundle. The bundle must be reproducible by an independent reviewer from the recorded source, environment description and instructions. Missing manifest fields, unverifiable hashes/signatures, skipped mandatory tests or absent persisted-state assertions fail the applicable gate.

**Additional acceptance tests**

- **C07-01:** generate a bundle from a completed adversarial run and verify every manifest reference resolves to immutable evidence.
- **C07-02:** alter an artifact after bundle creation; integrity verification detects the change.
- **C07-03:** omit a migration checksum, PostgreSQL build/configuration, exact source SHA or persisted-state assertion; bundle validation fails.
- **C07-04:** mark a mandatory test skipped or mocked; the relevant gate remains blocked.
- **C07-05:** independently reproduce the recorded test run and compare artifact hashes and persisted-state assertions.

### 20.8 Deployment profile additions and closure status

The companion YAML template must add explicit fields for:

- Cluster identity source/issuer, format, provisioning authority, persistence, clone/restore identity policy and duplicate-active-instance prevention.
- Mapping-store mode (`cluster_local` or `central`) and cluster-identity binding/verification method.
- Tombstone registry product/service identity, authority, consistency/sequence model, approved RPO, backup integrity and restore reconciliation.
- Canonical approval serialization version and digest algorithm; approval trust/verification profile, permitted algorithms/key types, minimum approver authentication assurance; requester, approver and executor separation; approval-ledger authority, consistency and recovery; signing-key rotation/revocation test evidence.
- JWT clock-skew value, trusted time source, synchronisation method, monitoring, drift alerting and failure policy.
- Maximum PostgreSQL role count, active credential count, rotation overlap and retained tombstone count.
- Three-option topology comparison and signed ADR evidence.
- Consolidated IC-07 evidence bundle URI, manifest URI, signature/integrity record, PostgreSQL build/configuration, migration checksums, effective privilege inventory, SECURITY DEFINER definitions/grants, RLS policy inventory, actual database identity/scope evidence and persisted-state assertions.

**Updated status:** IC-01-R5 through R7, IC-03-R3, IC-05-R2, IC-06-R3 and IC-07-R2 are addressed at contract/profile specification level only. All corresponding implementation, owner approval and runtime evidence remain outstanding. Gate 0 remains OPEN. No production deployment, customer production data, certification, SCADA/DMS connectivity or operational control is authorised.

**Release boundary:** This section is a documentation, profile and acceptance-test refinement only. It does not certify implementation, approve numerical deployment values, select the customer's topology, close Gate 0, authorise merge or permit deployment.


**Additional IC-07-R2 profile validation fields:** The profile's evidence section must separately reference SECURITY DEFINER definitions/owners/EXECUTE grants, effective role privileges, forced/enabled RLS policy inventory, actual `session_user`/cluster identity/scope resolution, persisted-state assertions, and signature/key verification tests. A generic evidence URI does not replace these typed references.
