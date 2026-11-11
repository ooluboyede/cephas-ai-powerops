# CEPHAS AI PowerOps 0.1.1 — Gate 0 Owner Decision Register

**Status:** DRAFT — OPEN; no deployment-owner decisions approved  
**Baseline:** Specification-approved commit `1671057a7633a50046af0722e7e2db2f61496662`  
**Purpose:** Capture deployment-specific decisions required by the 0.1.1 implementation contract before dependent implementation gates can pass.

> This is a decision register, not an approved deployment profile. Do not use it to configure or deploy a customer environment. IBDEC is the confirmed target customer for this draft. No identity provider, numeric limit, database topology, pooler, cryptographic authority, operational owner, or production permission is inferred here.

## Decision status convention

- **OPEN / TBD:** owner input and approval are outstanding.
- **PROPOSED:** a documented option exists but is not approved.
- **APPROVED:** only when the named accountable owner records an explicit decision and evidence.
- **NOT APPLICABLE:** requires a written rationale and approval by the accountable owner.

Every decision must record the deployment/customer, decision value, rationale, accountable approver (name and role), approval date, evidence/reference, implementation owner, and dependent gates. Blank fields remain blockers.

## 1. Deployment identity and authority

| Field | Current value | Required action |
|---|---|---|
| Initial customer / utility | **IBDEC** | Confirm the legal entity/deployment boundary and nominate accountable owners |
| Deployment environment and region | TBD | Customer-approved environment and residency |
| Customer security owner | TBD | Name and role |
| Customer DBA/platform owner | TBD | Name and role |
| Customer architecture owner | TBD | Name and role |
| PowerOps service owner | TBD | Name and role |
| PowerOps engineering owner | TBD | Name and role |
| Operational authority / escalation owner | TBD | Name and role; advisory-only until separately authorised |

## 2. IC-03-R2 — Execution and revocation

**Status: OPEN — blocks dependent Gate 1, Gate 5 and Gate 6 checks as applicable.**

| Decision | Approved value | Owner / evidence |
|---|---|---|
| Maximum transaction duration | TBD | Customer security owner + PowerOps service owner |
| Maximum query duration | TBD | Same |
| Maximum job duration | TBD | Same |
| New-work revocation propagation bound | TBD | Same |
| Query cancellation bound and semantics | TBD | Same |
| Session termination bound and semantics | TBD | Same |
| Positive membership-cache lifetime | TBD | Same |
| In-flight write policy (rollback or completion) | TBD | Same |
| Failure behaviour when revocation authority is unavailable | TBD | Same |

Required evidence: tests demonstrating revocation propagation, cancellation, session termination, cache expiry, and the approved in-flight write policy under normal and failure conditions.

## 3. IC-05-R1 — Capacity, connection budgets and pooler

**Status: OPEN — blocks dependent Gate 1 and Gate 5 checks.**

| Decision | Approved value | Owner / evidence |
|---|---|---|
| Target tenant count | TBD | Customer DBA/platform owner + PowerOps engineering owner |
| Target business-unit count | TBD | Same |
| Target scope count | TBD | Same |
| Target concurrent connections / workload profile | TBD | Same |
| Per-scope pool minimum and maximum | TBD | Same |
| Global connection budget | TBD | Same |
| Provisioning throughput target | TBD | Same |
| Credential/role rotation throughput target | TBD | Same |
| PostgreSQL product, exact version and configuration | TBD | Same |
| Pooler product, exact version and configuration | TBD | Same |
| Pooler mode and connection semantics | TBD | Same |
| Evidence that `session_user` is preserved as required | TBD | Same |

Required evidence: measured load/capacity results, pooler configuration, connection-budget calculation, and tests against the exact approved versions and mode. Do not select values from library defaults.

## 4. IC-06-R2 — Database topology and trust boundaries

**Status: OPEN — topology ADR required; blocks dependent Gate 0, Gate 1 and Gate 6 checks.**

Select and approve exactly one deployment topology:

- [ ] Shared database with scope-bound roles
- [ ] Separate databases in one PostgreSQL cluster
- [ ] Separate PostgreSQL clusters / instances
- [ ] Other (document and justify): TBD

| Decision | Approved value | Owner / evidence |
|---|---|---|
| Selected topology and ADR | TBD | Customer architecture/security owner |
| Tenant and business-unit trust boundaries | TBD | Same |
| Administrative and service trust boundaries | TBD | Same |
| Backup, restore and tenant-isolation design | TBD | Same |
| Disaster-recovery objectives and procedure | TBD | Same |
| Cross-tenant access prevention and verification | TBD | Same |
| Operational responsibilities and break-glass controls | TBD | Same |

Required evidence: approved architecture decision record, threat-boundary review, backup/restore tests, disaster-recovery evidence, and cross-tenant isolation tests.

## 5. IC-04-R4 — Endpoint and connection freshness

**Status: OPEN — blocks dependent Gate 4.**

| Decision | Approved value | Owner / evidence |
|---|---|---|
| Maximum DNS cache age | TBD | Customer platform/network owner + PowerOps engineering owner |
| Maximum absolute connection age | TBD | Same |
| Idle connection timeout | TBD | Same |
| Policy invalidation bound | TBD | Same |
| HTTP client and exact version | TBD | Same |
| HTTP/2 and connection-coalescing policy | TBD | Same |
| Proxy topology and evidence requirements | TBD | Same |

Required evidence: tests proving endpoint/policy changes take effect within approved bounds, including pooled connections, HTTP/2 behaviour and proxy paths.

## 6. IC-01-R4 — Identity, approval and fencing

**Status: OPEN — blocks dependent Gate 1.**

| Decision | Approved value | Owner / evidence |
|---|---|---|
| Approved identity provider | TBD | Customer identity/security owner |
| Stable human-subject uniqueness source | TBD | Same |
| Signature algorithm and key custody | TBD | Customer security owner + PowerOps service owner |
| Key rotation and compromise procedure | TBD | Same |
| Approval lifetime | TBD | Same |
| Replay-ledger authority, consistency and retention | TBD | Same |
| Strongly consistent fence authority | TBD | Same |
| Fence-authority outage/failure behaviour | TBD | Same |
| Named operational owners and escalation path | TBD | Customer operational owner + PowerOps service owner |

Required evidence: identity-provider configuration, subject uniqueness proof, key-custody/rotation procedures, replay tests, and fencing consistency/failure tests.

## 7. Release and operational guardrails

Until the relevant deployment profile and dependent gates are explicitly approved:

- Operations remain **advisory-only**.
- SCADA/DMS connectivity remains disabled.
- Dispatch, switching and protection controls remain disabled.
- Production data, production deployment and customer-network integration remain unauthorised.
- No operational activation or customer production use is permitted.
- No unresolved null, TBD or UNAPPROVED field may be treated as an implicit default.

## 8. Approval ledger

| Decision group | Required approver(s) | Decision | Evidence | Date |
|---|---|---|---|---|
| IC-03-R2 execution/revocation | Customer security owner; PowerOps service owner | OPEN | TBD | TBD |
| IC-05-R1 capacity/pooler | Customer DBA/platform owner; PowerOps engineering owner | OPEN | TBD | TBD |
| IC-06-R2 topology | Customer architecture/security owner | OPEN | TBD | TBD |
| IC-04-R4 endpoint freshness | Customer platform/network owner; PowerOps engineering owner | OPEN | TBD | TBD |
| IC-01-R4 identity/approval/fencing | Customer identity/security owner; PowerOps service owner | OPEN | TBD | TBD |

## 9. Gate 0 exit criteria

Gate 0 may be proposed for closure only after all of the following are true:

1. The first deployment customer is identified as **IBDEC**; accountable owner roles and named approvers are still outstanding.
2. All five decision groups above have complete, deployment-specific values.
3. Each decision has the required named owner approval and traceable evidence.
4. The deployment profile YAML is populated consistently with the approved register; no null/TBD/UNAPPROVED blocker remains for the applicable scope.
5. The IC-06 topology ADR is approved.
6. The implementation team maps each decision to its dependent acceptance tests and exact tested product/version/configuration.
7. Independent review confirms the evidence at the exact candidate commit.

**Target deployment: IBDEC. Current Gate 0 result: NOT SATISFIED — IBDEC owner decisions and approvals outstanding.**

Specification approval of the baseline does not approve this register, the deployment profile, implementation, customer integration, production release, or merge of PR #5.
