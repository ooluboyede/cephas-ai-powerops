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
- Selects shared database with scope-bound login roles/RLS or separate database per tenant.
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
