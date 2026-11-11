# CEPHAS AI PowerOps — Enterprise Dashboard Architecture and UI Specification 0.1.1

**Repository:** `ooluboyede/cephas-ai-powerops`  
**Workstream:** `pov/ibdec-readiness-audit`  
**Status:** DESIGN SPECIFICATION — NOT IMPLEMENTED, SECURITY-APPROVED, OR CUSTOMER-APPROVED  
**Applies to:** CEPHAS PowerOps Enterprise Edition and its configured customer PoV deployments  
**Related baseline:** `docs/IBDEC_POV_IMPLEMENTATION_BLUEPRINT_0.1.1.md`  
**Important naming note:** Existing repository material uses “IBEDC” in places while the current target has been stated as “IBDEC”. Confirm the customer's exact legal name before producing customer-facing material.

---

## 1. Purpose and governing product decision

This document defines the target architecture, navigation, screen behaviour, data presentation, API boundaries, authorization model and customer configuration for the CEPHAS AI PowerOps dashboard.

**The Enterprise Edition is the authoritative product.** The IBDEC PoV is a customer deployment profile of the same dashboard application and shared services. It is not a separate, reduced product codebase and must not create a permanent fork.

The same versioned dashboard components, domain APIs, authorization enforcement, data contracts, ML/Feature Engineering services and audit mechanisms serve both deployments. Customer configuration controls which approved modules, assets, metrics, users and features are visible. It does not weaken security controls or redefine the enterprise product.

The dashboard is an intelligence, monitoring and decision-support interface. It is **advisory-only**. No dashboard control may issue SCADA/ADMS/DMS commands, dispatch generation, perform switching, change protection settings or otherwise operate the electrical network.

## 2. Product principles

1. **Enterprise-first:** implement reusable enterprise capabilities; configure the PoV by deployment profile and entitlements.
2. **Server-side security:** enforce tenant, business-unit, site and resource access in identity, APIs, database queries, background jobs, exports and caches. UI filtering is never an authorization boundary.
3. **Evidence before inference:** display source, timestamp, freshness, quality, units, transformation/feature version and model provenance wherever relevant.
4. **Human accountability:** AI outputs are recommendations for qualified personnel to review; capture acknowledgement, disposition and rationale.
5. **Safe degradation:** missing, stale, invalid or unauthorised data must be clearly represented; never silently substitute fabricated or stale values.
6. **Explainability and uncertainty:** predictions must expose supported explanation, confidence/uncertainty and model status; suppress unsupported claims.
7. **Customer-hosted control:** customer data remains in the customer's approved environment under the agreed deployment architecture.
8. **Auditable operations:** material user actions, approvals, configuration changes, exports and model lifecycle events are attributable and tamper-evident.
9. **Accessible and responsive:** support desktop operational workstations and tablet layouts; critical status must not depend on colour alone.
10. **Licensed capability:** edition, modules, limits and validity are derived from the verified signed licence, not client-side flags.

## 3. Information architecture and navigation

The primary navigation is workspace-based. The navigation tree is filtered by server-issued permissions and verified licence entitlements; direct URL access is independently authorized.

| Workspace | Purpose | Enterprise availability |
|---|---|---|
| Executive Command Centre | Utility-wide operational and risk overview | Core |
| Grid Operations Intelligence | Feeder, transformer, substation and network indicators | Licensed module |
| Asset Intelligence | Asset condition, risk and maintenance prioritisation | Licensed module |
| Data Intelligence | Source health, ingestion, freshness and data quality | Core |
| AI & ML Intelligence | Model inventory, forecasts, anomalies, evaluation and drift | Licensed module |
| Feature Engineering | Feature catalogue, quality, lineage and version history | Licensed module |
| Alerts & Investigations | Alert triage, assignment, evidence and disposition | Core |
| Reports & Analytics | Historical analysis, reports and approved exports | Licensed module |
| Administration | Users, roles, tenants, business units and configuration | Permission-gated |
| Security & Audit | Security events, access reviews, audit and approvals | Permission-gated |
| Licensing & Deployment | Edition, module entitlements and deployment health | Permission-gated |

Navigation requirements:
- Provide a persistent tenant/customer and business-unit context indicator, populated from the authenticated server context.
- Show the active environment (for example, staging or production) conspicuously and never rely on colour alone.
- Provide global search only over resources the user is authorized to discover.
- Provide breadcrumbs, page titles, last-updated timestamps and contextual help.
- Hide inaccessible navigation entries for usability, but return an authorization error for direct access.
- Do not expose internal tenant IDs, secrets, signing material or infrastructure credentials in the browser.

## 4. Screen specifications

### 4.1 Executive Command Centre

**Audience:** executives, utility leadership, approved oversight roles.

**Purpose:** present a concise, trustworthy overview without implying operational control.

**Panels and widgets:**
- Utility overview: configured service areas, monitored assets and data-source coverage.
- Operational indicators: approved reliability, outage, load, loss or service metrics only where definitions and data are approved.
- Asset risk summary: counts by approved risk band, with data coverage and freshness.
- Alert summary: open, acknowledged, escalated and resolved counts over a selectable period.
- AI advisory summary: active advisory models, predictions awaiting review, drift warnings and suppressed outputs.
- Data trust panel: source availability, latest successful ingestion, stale feeds and quality exceptions.
- Trend charts with explicit time zone, units, sampling interval and missing-data gaps.
- Recent high-priority events and a link to the authorized investigation record.

**Interactions:** date range selection; drill-down to authorized asset/feeder/alert; export only with permission and audit. KPI definitions must be discoverable. Do not invent a KPI when source data or agreed calculation is absent.

### 4.2 Grid Operations Intelligence

**Audience:** authorized network operations and engineering personnel.

**Views:**
- Geographic or schematic overview only when validated geospatial/network topology is supplied and approved.
- Feeder list with status, latest measurement time, data quality and approved operational indicators.
- Feeder detail: time-series measurements, event timeline, related assets and data-quality annotations.
- Substation and transformer views where the deployment's asset model supports them.
- Comparison view for authorized feeders or periods, with unit and time alignment checks.

**Safety:** visual indicators are observational. No switching, dispatch, set-point, protection or SCADA write action is present. Any future operational-control requirement is a separate safety-critical product and architecture review, outside this specification.

### 4.3 Asset Intelligence

**Widgets:** asset register; asset profile; condition indicators; risk ranking; maintenance-priority queue; event and inspection history; data completeness.

**Requirements:**
- Every risk score shows calculation/model version, as-of timestamp, data coverage and uncertainty.
- Distinguish measured condition, deterministic rule result and ML-derived advisory.
- Permit authorized engineers to annotate, acknowledge or dispute a recommendation.
- Do not label an asset “failed” or “unsafe” solely from an unvalidated model prediction.
- Maintenance priority is advisory and requires human approval under customer procedures.

### 4.4 Data Intelligence

**Views:** source registry; ingestion runs; source connectivity status; schema validation; freshness/SLA status; data-quality findings; rejected records; reconciliation summaries.

**Required metadata:** source identifier, source owner, dataset, event time, ingestion time, time zone, unit, schema version, record count, validation outcome and trace/correlation identifier.

**Actions:** inspect authorized failure details, retry only where an approved retry workflow exists, assign a data-quality issue, and download a sanitized diagnostic report if permitted. Never expose credentials or raw secrets.

### 4.5 AI & ML Intelligence

**Views:**
- Model registry: model name, task, version, owner, approval state, signature verification state and deployment scope.
- Forecasting: forecast horizon, observed-vs-predicted values, uncertainty interval and evaluation status.
- Anomaly review: anomaly evidence, contributing signals/features where explainable, score, threshold/version and review status.
- Model performance: evaluation metrics with dataset window, baseline, sample size and limitations.
- Drift monitoring: feature/data drift, model performance drift and alert history.
- Inference provenance: input snapshot, feature-set version, model version, inference timestamp and execution trace.

**Controls:** model activation, promotion or rollback is restricted to explicitly authorized roles and must require the approval workflow defined by enterprise governance. A dashboard button must never bypass backend signature verification or deployment controls.

**Maturity stages:** data quality and deterministic indicators first; offline experiments next; shadow/advisory inference after validation; customer acceptance only after agreed evidence. A model that is unsigned, untrusted, stale, out of scope or failing validation is blocked from inference or clearly suppressed.

### 4.6 Feature Engineering

**Views:** feature catalogue; feature definition detail; transformation/version history; source-to-feature lineage; quality distribution; missingness and outlier summaries; dataset snapshots; point-in-time availability checks.

**Required feature metadata:** stable feature key, description, owner, data type, unit, source lineage, transformation version, event-time semantics, null policy, validation rules, tenant scope, creation/update time and approval status.

**Actions:** propose a feature definition, submit for review, compare versions and inspect lineage. Publishing or changing production feature definitions requires controlled review and immutable versioning. Prevent target leakage and cross-tenant feature contamination.

### 4.7 Alerts & Investigations

**Views:** prioritized queue; filters; alert detail; evidence timeline; related assets/events; assignment and escalation history; resolution/disposition.

**Workflow:** generated → triaged → acknowledged → assigned → under investigation → resolved or dismissed, with customer-configured states only if they preserve an auditable transition history.

**Actions:** acknowledge, assign, escalate, add note, attach approved evidence reference, record disposition. Each transition captures actor, time, prior/new state and reason where required. Do not permit destructive deletion of audit history.

### 4.8 Reports & Analytics

**Capabilities:** saved report definitions; time-series and aggregate analysis; approved operational summaries; model and data-quality reports; scheduled delivery where configured; CSV/PDF export subject to permissions.

**Controls:** enforce row-level authorization at report execution and export time; log who generated/exported which report, scope, time and format. Apply configurable retention, redaction and export limits. A report must disclose data coverage, time zone, filters and calculation version.

### 4.9 Administration

**Sections:** tenant and business-unit structure; users; role assignments; identity-provider configuration status; approved source configuration metadata; operational thresholds; notification preferences; retention settings; environment configuration summary.

**Controls:** least privilege, separation of duties, step-up authentication for sensitive actions, dual approval for designated high-impact changes, immutable audit event and safe rollback where supported. A user cannot grant themselves a role or expand their own tenant/resource scope.

### 4.10 Security & Audit

**Views:** authentication events; authorization denials; privileged actions; approval records; configuration changes; export history; model lifecycle events; licence validation events; audit integrity/retention status.

**Controls:** filters and detail views are permission-gated. Audit records are append-only from the application perspective, integrity-protected and exportable only to authorized reviewers. Never render secrets, password material, private keys or full authentication tokens.

### 4.11 Licensing & Deployment

**Display:** verified customer/tenant identity; edition; licensed modules; validity window; approved deployment/environment; approved limits; validator status; last successful validation; deployment health.

**Rules:** licence verification occurs server-side using the trusted licence authority and approved offline validation design. The browser receives only the minimum non-secret entitlement/status projection. Expired, invalid, revoked or scope-mismatched licences must fail closed for licensed functions while preserving explicitly permitted health, audit and renewal information. Never display or log signing private keys or complete licence secrets.

## 5. Shared page layout and interaction patterns

Standard page structure:
1. Global application header: product, environment, authorized tenant context, user menu.
2. Workspace navigation.
3. Breadcrumb and page title with concise description.
4. Page-level filters, whose values are validated server-side.
5. Main content grid of cards, tables, charts and detail panels.
6. Persistent provenance/freshness indicators for data-dependent content.
7. Accessible loading, empty, stale, partial, error and permission-denied states.

Interaction requirements:
- Tables: server-side pagination, sorting and filtering; stable row identifiers; no client-side fetch of unauthorized rows.
- Charts: explicit units, time zone, interval, legend, accessible text alternative and missing-data indication.
- Drill-down: preserve authorized filters and context without trusting URL parameters.
- Forms: server-side validation, CSRF protection where applicable, idempotency for mutation requests and clear confirmation for material actions.
- Long-running operations: asynchronous job status with owner/scope checks on every poll and result retrieval.
- Notifications: do not include sensitive record content in browser push/email unless approved by customer policy.
- Session expiry: clear sensitive views and require re-authentication; do not silently continue privileged actions.

## 6. Conceptual API contract

These are proposed logical API boundaries, **not evidence that endpoints currently exist**. Final paths, schemas and transport conventions must be confirmed during implementation design.

| Capability | Proposed operation | Read/write |
|---|---|---|
| Dashboard summary | `GET /api/v1/dashboard/summary` | Read |
| KPI series | `GET /api/v1/metrics/series` | Read |
| Asset list/detail | `GET /api/v1/assets`, `GET /api/v1/assets/{id}` | Read |
| Feeder list/detail | `GET /api/v1/feeders`, `GET /api/v1/feeders/{id}` | Read |
| Data-source health | `GET /api/v1/data-sources/health` | Read |
| Data-quality findings | `GET /api/v1/data-quality/findings` | Read |
| Feature catalogue | `GET /api/v1/features` | Read |
| Feature version proposal | `POST /api/v1/features/proposals` | Write, approval-gated |
| Model registry | `GET /api/v1/models` | Read |
| Model evaluation | `GET /api/v1/models/{id}/evaluations` | Read |
| Advisory predictions | `GET /api/v1/predictions` | Read |
| Alert queue/detail | `GET /api/v1/alerts`, `GET /api/v1/alerts/{id}` | Read |
| Alert acknowledgement | `POST /api/v1/alerts/{id}/acknowledgements` | Write, permission-gated |
| Investigation assignment | `POST /api/v1/investigations/{id}/assignments` | Write, permission-gated |
| Reports | `GET /api/v1/reports`, `POST /api/v1/reports/runs` | Mixed |
| Audit search | `GET /api/v1/audit-events` | Read, restricted |
| Licence status | `GET /api/v1/licence/status` | Read, restricted |

### API invariants

- Derive tenant and business-unit context from verified server-side identity/session claims; never accept client-supplied tenant scope as authority.
- Validate resource-level access on every request, including nested resources, exports, downloads, websocket/subscription channels and job results.
- Enforce database-level tenant isolation (PostgreSQL RLS where applicable) in addition to application authorization. Fail closed if tenant context is absent or invalid.
- Use parameterized queries, schema validation, bounded pagination and request-size limits.
- Use idempotency keys for retriable mutations and stable correlation IDs for traceability.
- Return safe error messages without leaking resource existence across tenant boundaries.
- Apply rate limits and step-up authentication to sensitive operations.
- Version APIs and event schemas; maintain backward compatibility within the declared support policy.
- All mutation endpoints create attributable audit events.
- No API in this dashboard specification may write to SCADA/ADMS/DMS or control network equipment.

## 7. Authorization and role model

The final role catalogue is customer-approved configuration. The following is a minimum role design, not a grant of access:

| Role | Typical access | Restrictions |
|---|---|---|
| Executive Viewer | Executive dashboard, approved reports | Read-only; no raw sensitive data by default |
| Operations Viewer | Grid and asset views | Authorized resource scope only |
| Operations Engineer | Operational indicators, alert review and annotations | Advisory actions only; no control-plane actions |
| Data Engineer | Data health, quality and feature lineage | No automatic production model promotion |
| ML Engineer | Model/feature experiments and evaluation | No unilateral production approval |
| Model Approver | Review and approve model releases | Separate from author/deployer where required |
| Investigator | Assigned alerts and evidence | Case/resource scope only |
| Auditor | Security, audit and approved reports | Read-only; export controlled |
| Tenant Administrator | Users and tenant configuration | Cannot bypass platform controls or self-elevate |
| Platform Operator | Deployment health and platform administration | Customer data access restricted and audited |
| Licence Administrator | Licence status and renewal workflow | No access to signing private keys |

Authorization is a combination of role, tenant, business unit, site/resource scope, action, licence entitlement and environment. Deny by default. Enforce separation of duties for model approval, privileged administration and sensitive exports. The same identity must not author and independently approve its own high-impact change where separation is required.

## 8. Data and provenance requirements

Every operational observation must preserve, where available:
- Source system and source record identifier.
- Tenant/business-unit/resource scope.
- Event timestamp, ingestion timestamp and timezone semantics.
- Measurement value, unit and quality/status flag.
- Schema and mapping version.
- Data-quality validation result.
- Trace/correlation identifier.

Every derived metric, feature or prediction must additionally preserve:
- Calculation or transformation version.
- Input dataset/snapshot reference and lineage.
- Feature-set version and point-in-time cutoff where applicable.
- Model identifier/version and cryptographic verification status where applicable.
- Inference/evaluation timestamp.
- Confidence/uncertainty and supported explanation, or explicit statement that these are unavailable.
- Human review state and reviewer attribution, where reviewed.

The UI must distinguish **unknown**, **not collected**, **stale**, **invalid**, **suppressed** and **zero**. These states are not interchangeable.

## 9. Enterprise versus IBDEC PoV configuration

| Dimension | Enterprise Edition | IBDEC PoV profile |
|---|---|---|
| Product code | Shared enterprise dashboard and APIs | Same versioned code |
| Customer scope | Multiple licensed customers/tenants as deployment architecture permits | One approved customer scope |
| Business units | Configurable hierarchy and isolation | Only agreed pilot units |
| Navigation | Licensed and authorized enterprise workspaces | Approved subset, same components |
| Data sources | Customer-approved integrations | Explicitly approved PoV sources only |
| Assets | Tenant-authorized inventory | Pilot asset/feeder subset |
| ML/Feature Engineering | Full governed platform capability according to licence | Approved data quality, feature and validated advisory stages |
| Model actions | Governed by enterprise approvals | Shadow/advisory only unless separately approved |
| Reports/exports | Enterprise policy and entitlements | PoV-approved outputs and retention |
| Licence | Enterprise edition and signed module entitlements | Time-limited, scope-limited signed PoV licence |
| Security | Full enterprise security baseline | Same controls; no PoV security downgrade |
| Network control | Not included | Explicitly prohibited |

PoV-specific restrictions are enforced by deployment configuration, licence, server authorization and data scope. They must not be implemented as hard-coded customer branches in shared components. No PoV data, model, user, or configuration may be visible to another tenant.

## 10. Non-functional requirements

Implementation teams must convert these into measurable acceptance criteria before release. No numerical SLO is assumed here because capacity, deployment topology and customer workload have not yet been approved.

- **Security:** threat model, secure coding review, dependency scanning, authentication/authorization tests, tenant isolation tests, audit verification and independent security review.
- **Performance:** documented workload model; measured API and dashboard latency under representative concurrency and data volume; bounded queries and pagination.
- **Availability and resilience:** customer-approved service objectives, health/readiness semantics, backup/restore and failure-mode tests.
- **Scalability:** tenant/resource partition strategy, asynchronous processing and cache isolation.
- **Observability:** structured logs, metrics and traces with correlation IDs; no secrets or unnecessary personal data in telemetry.
- **Accessibility:** keyboard navigation, screen-reader labels, contrast, focus handling and non-colour status indicators.
- **Compatibility:** supported browser matrix and customer workstation constraints documented.
- **Localization:** explicit timezone handling, locale-aware number/date formatting and consistent engineering units.
- **Maintainability:** versioned API contracts, component tests, integration tests, end-to-end tests and documented upgrade/rollback.
- **Data governance:** retention, minimization, export, deletion and residency controls approved by customer.

## 11. Security and safety acceptance gates

The dashboard must not be accepted for customer deployment until evidence demonstrates:

1. Authentication and session lifecycle work as specified.
2. Tenant and business-unit context is server-verified and fail-closed.
3. Database isolation is enforced and tested, including cross-tenant negative tests.
4. Resource-level authorization applies to APIs, dashboards, exports, jobs, caches and subscriptions.
5. Privileged actions enforce step-up/approval/separation-of-duties rules.
6. Audit events are complete, attributable and integrity-protected.
7. Model signatures are verified before deserialization; untrusted/tampered artifacts are rejected.
8. Feature and dataset lineage, point-in-time correctness and leakage controls are tested.
9. Stale/invalid/missing data and model drift are visibly and safely handled.
10. Licence validity, scope, revocation and offline validation behaviour are tested.
11. No network-control endpoint or UI action is exposed.
12. Independent security review and customer PoV acceptance evidence are recorded.

## 12. Proposed implementation sequence

This is a proposed order, not a statement of completed work:

- **D0 — Specification review:** product owner, security reviewer and engineering owner approve this specification and resolve open decisions.
- **D1 — Design system and shell:** authenticated shell, navigation, environment/context indicators, accessible component primitives.
- **D2 — Identity and authorization foundation:** server-side tenant/BU context, roles, resource scopes, database isolation and negative tests. This precedes customer data.
- **D3 — Read-only operational data contracts:** assets, feeders, measurements, events, freshness and quality.
- **D4 — Executive and operational read-only workspaces:** summary, grid and asset views using synthetic/test data first.
- **D5 — Data Intelligence and audit:** ingestion health, quality findings and audit views.
- **D6 — Shared ML and Feature Engineering workspaces:** feature catalogue, dataset lineage, model registry, evaluation and advisory presentation.
- **D7 — Alerts, investigations and reporting:** audited workflows, scoped exports and retention controls.
- **D8 — Licensing and deployment integration:** signed entitlements, offline validation and scope enforcement.
- **D9 — End-to-end security and usability verification:** exact-head CI, tenant isolation, accessibility, performance and independent review.
- **D10 — Customer PoV configuration and acceptance:** only after customer identity, data sources, owners, scope, success criteria and approvals are documented.

Do not skip D2 to accelerate visual delivery. A visually complete dashboard without verified identity, tenant isolation and authorization is not a customer-ready product.

## 13. Required design and customer decisions

The following remain open and must be resolved by authorized owners:
- Confirm customer legal name and whether “IBDEC” is the correct customer-facing name.
- Confirm customer identity provider, MFA policy and user lifecycle.
- Confirm tenant/business-unit/site hierarchy and named data owners.
- Approve source systems, data fields, data transfer method and retention.
- Approve operational KPI definitions, units, thresholds and time-zone conventions.
- Confirm supported asset types and topology/geospatial availability.
- Confirm which ML use cases have sufficient approved data and acceptance criteria.
- Confirm model approval/deployment roles and separation of duties.
- Confirm dashboard browser/device requirements and accessibility expectations.
- Confirm report/export permissions, formats, retention and delivery channels.
- Confirm deployment environment, capacity, backup/restore and support objectives.
- Confirm PoV duration, licensed scope, success criteria and exit/data-handling plan.

No missing decision is to be filled with an invented customer fact or arbitrary threshold.

## 14. Explicit exclusions

This specification does not establish that any dashboard, API, integration, model, feature pipeline, licence validator or security control has been implemented. It does not authorize:
- Customer installation, production use or connection to customer systems.
- Ingestion of live IBDEC/IBEDC operational data.
- SCADA/ADMS/DMS write access, dispatch, switching, protection or remote control.
- Automatic maintenance orders or autonomous operational decisions.
- Production ML activation without data, validation, signature and approval evidence.
- A reduction in enterprise security controls for the PoV.

## 15. Definition of done for this specification

This document is ready for independent design review when reviewers can assess the product boundary, navigation, screen requirements, conceptual API boundaries, authorization model, provenance, enterprise/PoV relationship and acceptance gates.

It is **not** a release approval. Approval of this document authorizes only the next design/implementation planning gate, not customer deployment.

---

**End of specification.**
