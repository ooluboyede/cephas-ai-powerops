# CEPHAS AI PowerOps 0.1.1 — IBDEC Gate 0 Technical Decision Session Pack

**Document status:** DRAFT — FOR CUSTOMER TECHNICAL WORKSHOP  
**Target deployment:** IBDEC  
**Baseline specification:** `1671057a7633a50046af0722e7e2db2f61496662`  
**Working branch:** `docs/0.1.1-gate-0-owner-decision-register`  
**Release status:** Gate 0 OPEN; implementation and production authorisation remain blocked.

---

## 1. Purpose and required outcome

This pack is for a structured decision session between IBDEC's nominated technical/security owners and CEPHAS AI Solutions. Its purpose is to obtain deployment-specific decisions and evidence required by the PowerOps 0.1.1 implementation contract.

The session must produce:
1. A named IBDEC and CEPHAS decision-owner roster.
2. A decision for each applicable Gate 0 decision group, or a clearly assigned action with an owner and due date.
3. An agreed evidence plan for each decision.
4. A list of unresolved assumptions, dependencies and risks.
5. A controlled path to update the IBDEC deployment profile and ADR-PWR-001 after owner approval.

**The meeting is not an approval by attendance.** No value is approved unless the accountable owner explicitly records the decision and its evidence. A verbal preference, meeting note, engineering suggestion or vendor default is not deployment-owner approval.

## 2. Scope and non-scope

### In scope
- IC-03-R2: execution limits, revocation, cancellation and in-flight writes.
- IC-05-R1 / related IC-05 capacity controls: workload sizing, database connection and role budgets, PostgreSQL/pooler selection and conformance.
- IC-06-R2 / IC-06-R3: topology comparison and signed ADR-PWR-001.
- IC-04-R4: endpoint freshness, HTTP client/pooling and proxy evidence.
- IC-01-R4 and related identity/fencing requirements: OIDC, human identity uniqueness, approval signing/key lifecycle, replay ledger and fencing authority.
- Dependencies called out by the contract, including cluster identity/tombstone lifecycle, exceptional-removal actor separation, time synchronisation and the consolidated runtime evidence bundle.

### Explicitly out of scope
This workshop does not authorise:
- Production deployment, production data, or connection to IBDEC's live operational network.
- SCADA/DMS connectivity, dispatch, switching, protection or other control actions.
- Remote control or autonomous operational action.
- Bypassing customer change control, security review, procurement, regulatory review or operational safety processes.
- Treating the template profile or this workshop pack as a deployable configuration.

Until separate written approvals and release gates are complete, PowerOps remains **advisory-only** and all operational-control integrations remain disabled.

## 3. Required participants and decision rights

IBDEC should nominate named individuals (name, title, department, contact and delegated authority) for these roles:

| Role | Required contribution / decision authority |
|---|---|
| IBDEC executive sponsor / service owner | Confirms business sponsor, scope, accountable service owner and escalation route; does not replace technical approvals |
| IBDEC CISO delegate / security owner | Approves security risk, revocation/failure policy and security control decisions within delegated authority |
| IBDEC IAM / directory owner | Approves OIDC provider/issuer, subject uniqueness source, identity proofing and authentication assurance |
| IBDEC DBA / database platform owner | Approves PostgreSQL build/configuration, pooler, role/connection budgets, HA and database operating model |
| IBDEC enterprise architect | Owns architecture comparison and approval of ADR-PWR-001 with the required security authority |
| IBDEC network / infrastructure security owner | Approves DNS, HTTP client, proxy/network path and endpoint freshness/evidence requirements |
| IBDEC operations / control-room authority | Defines operational boundaries, advisory-only use, escalation, emergency access and prohibited actions |
| IBDEC backup / DR owner | Approves backup custody, restore, RTO/RPO, failover and recovery evidence |
| CEPHAS PowerOps service owner | Owns service-side decisions, support model, revocation semantics and operational accountability |
| CEPHAS engineering owner | Maps approved decisions to implementation, exact-version tests and evidence bundles |
| CEPHAS security architect / reviewer | Explains threat model and verifies security evidence; cannot approve IBDEC-owned values on IBDEC's behalf |
| Independent reviewer (as appointed) | Independently reviews exact commit, configuration, tests and evidence; does not substitute for customer approval |

One person may hold more than one role only if IBDEC confirms the delegation and any required separation-of-duties controls remain satisfied. Exceptional approval/requester/approver/executor separation requirements cannot be waived by workshop convenience.

## 4. Pre-session information request

IBDEC participants should bring or provide through an approved secure channel:

1. Confirmed legal customer/entity name and deployment identifier to use in the profile.
2. Names and delegated approval authority for the roles in Section 3.
3. Target environment classification (non-production only for this phase), hosting responsibility, location/data-residency constraints and network boundary diagram.
4. Current or intended identity provider details: product, issuer, tenant/realm, stable immutable person identifier and MFA/authentication assurance capabilities. Do not send passwords, tokens, private keys or secrets.
5. Database platform standards: approved PostgreSQL versions/builds, HA/replication standards, backup/restore platform and any approved pooler options.
6. Workload estimates or source data for users, tenants, business units, scopes, API traffic, protected transactions, jobs, audit events, provisioning and credential rotation.
7. DNS, outbound network, proxy, TLS inspection and HTTP client standards relevant to outbound identity metadata/JWKS retrieval.
8. Customer retention, audit, incident response, emergency access and change-management requirements.
9. Backup/DR requirements and available recent test evidence, where shareable.
10. Any IBDEC security architecture standards, threat models, policies or constraints applicable to this non-production advisory deployment.

**Information handling:** exchange architecture and evidence only through IBDEC-approved channels. Do not place credentials, private keys, personal data, production records, sensitive network secrets or unredacted security logs in this repository or ordinary meeting minutes.

## 5. Proposed 150-minute agenda

| Time | Topic | Lead | Required output |
|---|---|---|---|
| 00–10 min | Opening, scope, safety boundaries and decision rules | Joint chairs | Scope and non-scope acknowledged |
| 10–20 min | IBDEC deployment identity, environment and owner roster | IBDEC sponsor | Customer identifier and named owner/action list |
| 20–45 min | IC-06 topology options and trust boundaries | IBDEC architect + CEPHAS architect | Preferred option for evaluation; ADR actions; no premature approval |
| 45–70 min | IC-05 capacity, PostgreSQL, pooler and role budgets | IBDEC DBA + CEPHAS engineering | Workload inputs, exact platform candidates, measurement plan |
| 70–90 min | IC-03 execution, revocation and in-flight work | IBDEC security + CEPHAS service owner | Proposed limits/policies and required failure tests |
| 90–110 min | IC-01 identity, approvals, replay, fencing and time | IBDEC IAM/security + CEPHAS security | Identity/fencing decision actions and evidence plan |
| 110–125 min | IC-04 endpoint freshness, DNS, HTTP/2 and proxy | IBDEC network security + CEPHAS engineering | Client/network policy actions and test evidence |
| 125–140 min | Recovery, operations, evidence bundle and change control | IBDEC operations/DR + CEPHAS | RTO/RPO, operational boundaries and evidence owners |
| 140–150 min | Read-back, action owners, due dates and close | Joint chairs | Decision log read back; unresolved items assigned |

If owners or evidence are unavailable, record the item as OPEN and assign a follow-up. Do not force a decision to fit the meeting slot.

## 6. Decision worksheets

For every decision below, record: **decision ID; exact value or selected option; units and scope; rationale; alternatives considered; accountable IBDEC approver; CEPHAS implementation owner; date; evidence URI/reference; dependent gate(s); status.** Use OPEN where any element is missing.

### A. IC-06-R2 / IC-06-R3 — Topology and trust boundaries

Compare all three contract alternatives; do not assume the recommended reference model is already approved:

1. Shared database with scope-bound roles and RLS.
2. Separate databases within one PostgreSQL cluster.
3. Separate PostgreSQL clusters or independently administered instances.

Decisions and evidence:
- Selected topology and signed ADR-PWR-001.
- Tenant, business-unit, scope, service and administrator trust boundaries.
- Threat model and rejected alternatives with rationale.
- Staging/production separation and migration/rollback approach.
- Backup custodian, backup policy, restore test, DR plan, RTO and RPO.
- Failover behaviour and cross-tenant analytics isolation.
- Operating responsibilities, privileged access and break-glass controls.
- Deployed-topology conformance evidence.

**Required output:** ADR owner, comparison-matrix owner, threat-model owner and target approval date. The topology remains unapproved until the authorised IBDEC architecture/security authority signs the ADR.

### B. IC-05-R1 and associated capacity controls — Capacity and database/pooler

Capture measurable workload assumptions, not estimates disguised as approvals:
- Tenant count; business units per tenant; tenant-wide scopes; active scopes.
- Peak concurrent users, API requests, protected transactions and jobs.
- Peak audit events/second; expected database size and annual growth.
- Database connection limit and administrative reserve.
- Per-scope pool minimum/maximum and global pool budget.
- Provisioning events/hour; credential rotations/day.
- Exact PostgreSQL product, major/minor build and configuration.
- Exact pooler product/version, mode and configuration.
- Pool exhaustion/backpressure behaviour and no shared-login fallback.
- Scope-bound login-role ceiling versus total cluster-wide role ceiling; platform/service reserve and reserved slots.
- Measured preservation of PostgreSQL `session_user` through the chosen pooler and connection mode.

**Required output:** workload model, capacity calculation, selected platform versions, configuration evidence and load/conformance test plan. No connection, role, pool or throughput value may be taken from a library default without owner approval.

### C. IC-03-R2 — Execution and revocation policy

IBDEC security owner and CEPHAS service owner must agree:
- Maximum transaction duration.
- Maximum query duration.
- Maximum job duration.
- Maximum positive membership-cache lifetime.
- Maximum new-work revocation propagation time.
- Query cancellation, session termination and job cancellation bounds.
- In-flight write policy: rollback or bounded completion, with maximum completion bound if applicable.
- Behaviour when the revocation/fence authority is unavailable.

**Required output:** explicit numeric limits with units, policy rationale, owner approval and runtime test cases for normal operation, timeout, cancellation, outage and race conditions.

### D. IC-01-R4 and related identity/fencing controls

Decisions:
- OIDC provider, exact issuer and audience, provider profile and stable immutable human-subject uniqueness source.
- Method to verify distinct human persons for separated approval roles.
- Approved signature algorithms/key types; signing-key custodian; key custody, rotation and revocation procedures.
- Exceptional approval maximum age/lifetime and minimum approver authentication assurance.
- Replay-ledger authority/product, consistency, atomic consumption, uniqueness/idempotency, durability and failover semantics.
- Strongly consistent retirement-fence authority, lock protocol, transaction isolation, lock ordering/timeout, deadlock and retry policy.
- HA mode, synchronous replication/quorum policy, synchronous-commit setting and durability evidence.
- Former-primary write fencing, promotion/reconciliation barrier and ambiguous-commit recovery.
- Cluster identity source, uniqueness, clone/restore identity policy and duplicate-active-instance prevention.
- Tombstone registry authority, append-only integrity, sequence/commit model, independent backup and restore reconciliation.
- Requester/approver/executor identities and required distinct-principal separation for exceptional removal.
- Trusted time source, synchronisation method, monitoring, drift alert and approved JWT clock-skew bound.

**Required output:** IAM profile, key lifecycle and assurance evidence, replay/atomic-consumption test plan, fencing/HA test plan, cluster/tombstone lifecycle plan and named operational owners. No private key or secret is to be exchanged in the meeting.

### E. IC-04-R4 — Endpoint and connection freshness

Decisions:
- HTTP client product and exact version.
- Maximum DNS cache age.
- Maximum absolute connection age.
- Idle connection timeout.
- Maximum policy invalidation delay.
- HTTP/2 enablement and cross-origin connection-coalescing policy.
- Proxy mode; if enabled, exact proxy product/version and authenticated, tamper-resistant evidence requirements, retention and retrieval.
- Exact normalized HTTPS discovery and JWKS origins and issuer-bound endpoint/path policy.
- Redirect, prohibited-destination, DNS-rebinding, actual socket peer and TLS identity test evidence.

**Required output:** approved endpoint policy and exact-client test plan. Proxy use is not approved merely because the proxy is present; the required upstream destination evidence must be verifiable and correlated to the fetch.

### F. Operational, audit and evidence requirements

Confirm:
- Advisory-only use cases and explicit prohibited operational actions.
- Customer security contact, PowerOps security contact and incident escalation.
- Emergency access and two-person controls.
- Audit retention and integrity-verification requirements.
- Backup/restore/DR operational ownership.
- Evidence bundle storage, access, integrity hash/signature, retention and independent reproduction requirements.
- Change control and approval process for any later profile modification.

**Required output:** named operational owners, runbook/evidence owners and written confirmation that no control-system or production access is being authorised by this workshop.

## 7. Decision record template

Copy this block once per decision. Do not set status to APPROVED until all required approvals and evidence are recorded.

| Field | Entry |
|---|---|
| Decision ID / contract reference | TBD |
| Deployment | IBDEC — exact deployment ID TBD |
| Decision statement | TBD |
| Exact value / selected option / units | TBD |
| Scope and assumptions | TBD |
| Rationale and alternatives | TBD |
| IBDEC accountable approver (name/title) | TBD |
| Evidence reference / URI | TBD |
| CEPHAS implementation owner | TBD |
| Dependent gate(s) | TBD |
| Decision date (UTC) | TBD |
| Status | OPEN |

## 8. Action log template

| Action ID | Action / evidence required | Owner (named person) | Due date | Dependency | Status |
|---|---|---|---|---|---|
| A-001 | Confirm IBDEC deployment ID and environment boundary | TBD | TBD | Owner nomination | OPEN |
| A-002 | Nominate and confirm delegated decision owners | TBD | TBD | IBDEC sponsor | OPEN |
| A-003 | Supply workload/capacity inputs | TBD | TBD | DBA/platform owner | OPEN |
| A-004 | Supply IAM/OIDC and human identity uniqueness profile | TBD | TBD | IAM/security owner | OPEN |
| A-005 | Supply PostgreSQL/pooler candidates and platform standards | TBD | TBD | DBA/platform owner | OPEN |
| A-006 | Complete three-option topology comparison and ADR-PWR-001 | TBD | TBD | Architecture/security owner | OPEN |
| A-007 | Agree execution/revocation policy and test limits | TBD | TBD | Security + service owners | OPEN |
| A-008 | Agree endpoint/network policy and proxy evidence | TBD | TBD | Network/security owner | OPEN |
| A-009 | Agree backup/restore/DR evidence and operational boundaries | TBD | TBD | DR + operations owners | OPEN |
| A-010 | Update profile and map approved decisions to tests | TBD | TBD | All approvals | BLOCKED |

## 9. Gate 0 closure checklist

Gate 0 is not complete until all applicable items are satisfied and independently traceable:

- [ ] IBDEC legal customer/entity and deployment identifier are confirmed.
- [ ] Named decision owners and delegated approval authority are recorded.
- [ ] IC-03 execution/revocation values and policies are approved and testable.
- [ ] IC-05 workload, capacity, role/connection budgets, PostgreSQL and pooler details are approved and measurable.
- [ ] IC-06 three-option comparison and signed ADR-PWR-001 are complete.
- [ ] IC-04 endpoint freshness, HTTP client, HTTP/2 and any proxy evidence requirements are approved.
- [ ] IC-01 identity, human uniqueness, approval assurance, signing/key lifecycle, replay ledger, fencing and outage/failover decisions are approved.
- [ ] Related cluster identity/tombstone, exceptional-removal and clock-synchronisation decisions are resolved.
- [ ] IBDEC deployment profile is populated consistently; no applicable null/TBD/UNAPPROVED field is silently treated as a default.
- [ ] Required runtime, load, adversarial, recovery and conformance tests are mapped to exact approved versions/configuration.
- [ ] Evidence is stored in the approved location and referenced from the version-controlled profile.
- [ ] Independent reviewer has reviewed the exact candidate commit and evidence.
- [ ] Separate release authorisation is recorded by the appropriate authorities.

**Current result: NOT SATISFIED.** This pack prepares the customer decision process; it does not approve any decision or release gate.

## 10. Suggested invitation text

**Subject:** CEPHAS AI PowerOps 0.1.1 — IBDEC Technical Decision Workshop (Gate 0)

IBDEC colleagues,

CEPHAS AI Solutions is proposing a technical decision workshop for the PowerOps 0.1.1 advisory platform deployment targeted at IBDEC.

The purpose is to review and document the customer-owned decisions required before implementation gates can be completed. Topics include deployment topology and trust boundaries, database capacity and pooler configuration, execution/revocation limits, identity and approval controls, endpoint/network security, and backup/recovery evidence.

Please nominate the relevant IBDEC security/IAM, DBA/platform, enterprise architecture, network security, operations and backup/DR representatives, including the individuals authorised to approve decisions in their respective areas.

We propose a 150-minute session. The attached decision-session pack sets out the agenda, required pre-read information and decision records. Please share only non-secret architecture and policy information through IBDEC-approved channels; do not send credentials, private keys, tokens or production data.

For clarity, this workshop does not request or grant production deployment, production-data access, SCADA/DMS connectivity or dispatch/switching/protection authority. The platform remains advisory-only while the required approvals, implementation evidence and independent reviews are outstanding.

Please confirm the nominated participants and suitable meeting times.

Regards,  
CEPHAS AI Solutions  
PowerOps Engineering
