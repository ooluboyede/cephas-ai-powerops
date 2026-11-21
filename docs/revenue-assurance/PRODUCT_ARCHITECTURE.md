# PowerOps Revenue Assurance Agent — Product & Engineering Architecture

**Status:** Phase 0 foundation specification  
**Product:** CEPHAS PowerOps Revenue Assurance Agent  
**Initial design partner:** IBEDC, followed by other electricity distribution companies (DisCos)  
**Market:** Worldwide; country, utility, currency, tax and regulatory configuration required  
**Deployment:** Customer-hosted and CEPHAS-managed cloud  
**Decision boundary:** Advisory and workflow automation only. No autonomous disconnection, billing adjustment, refund, journal posting, meter command, switching, dispatch or protection action.

## 1. Product promise

PowerOps helps utilities identify, quantify, investigate and reduce revenue leakage. It links source evidence from metering, vending, billing, payments, customer, feeder and field systems; detects anomalies; explains the evidence behind each case; recommends controlled actions; and tracks approved recovery through closure.

PowerOps must distinguish:
1. **Observed facts** — immutable source records and their provenance.
2. **Calculated measures** — deterministic calculations with versioned formulas.
3. **Model findings** — probabilistic scores, anomaly indicators and confidence.
4. **Human-validated conclusions** — decisions approved by authorised utility personnel.

Never present a model score as proof of theft, fraud or customer liability.

## 2. Initial product modules

- Revenue Gap Intelligence: compare energy supplied, billed, vended and collected over aligned periods and boundaries.
- Meter & Consumption Intelligence: identify zero/flatline, reverse, tamper-signal, bypass-indicator, abnormal load-profile and meter-to-account mismatches where source data supports them.
- Billing Assurance: detect missing bills, estimated-billing anomalies, tariff/rate mismatches, duplicate bills, unexplained adjustments and billing-to-meter discrepancies.
- Vending & Payment Reconciliation: reconcile vending, payment gateway, bank settlement, wallet and customer ledger records; identify unmatched, delayed, duplicated and reversed transactions.
- Feeder / Transformer Loss Context: correlate technical loss indicators and asset/network context with commercial loss signals. Keep technical and non-technical loss hypotheses separate.
- Investigation Case Management: evidence pack, timeline, reason codes, assigned owner, due date, review and disposition.
- Recovery Workflow: recommended action, approval, execution evidence, recovered amount, reversals, dispute and closure.
- Executive Command Centre: verified KPIs, trend, exposure bands, case ageing, recovery funnel and model performance.

## 3. Agent roles and permissions

| Agent | Read/analysis responsibility | Permitted output |
|---|---|---|
| Revenue Intelligence | Reconcile energy, billing, vending and collection aggregates | Revenue-gap hypotheses and ranked exceptions |
| Meter Intelligence | Analyse meter events and interval/period consumption | Meter anomaly indicators with supporting observations |
| Billing Assurance | Compare bills, tariffs, reads and account history | Billing exception recommendations |
| Payment Reconciliation | Match payment, settlement, vending and ledger records | Unmatched/reversal/duplicate candidates |
| Loss Context | Correlate feeder, transformer and inspection context | Separate technical/non-technical loss hypotheses |
| Investigation | Assemble source-linked chronology and evidence | Human-review case pack |
| Recovery | Track approved actions and actual outcomes | Draft recovery workflow and follow-up tasks |
| Executive | Aggregate validated metrics and trends | Management reports with data-quality caveats |

All agent actions are scoped by tenant, business unit, geography, role and licensed module. The model cannot grant itself permissions or call unapproved tools. Tool execution is allowlisted, schema-validated and policy-checked.

## 4. Reference architecture

### Shared logical services
- API gateway / BFF with OIDC authentication, MFA, RBAC/ABAC and tenant context.
- Ingestion gateway for batch CSV/XLSX, secure file drop, REST/webhooks and later customer-approved connectors.
- Schema registry and canonical data contracts with source system, source record ID, event time, ingestion time, unit, currency, quality status and provenance.
- Validation and quarantine pipeline; malformed, duplicate, late and out-of-range records are observable and never silently discarded.
- Raw evidence store (immutable/retention-controlled), normalized operational store, analytical feature store and case/workflow store.
- Deterministic calculation service for energy and money reconciliation.
- Rules engine plus anomaly/model services; every rule/model version is recorded with each finding.
- Agent orchestrator with constrained tools, policy gateway, approval service and bounded retries.
- Case management, notification, reporting and audit services.
- Observability: structured logs, metrics, traces, model/data drift and security events.

### Logical data flow
1. Receive customer-approved source data.
2. Authenticate source, validate schema, preserve original evidence and provenance.
3. Normalize units, time zones, account/meter/network identifiers and currency without overwriting source values.
4. Run deterministic reconciliation and data-quality checks.
5. Generate explainable rule/model findings.
6. Create or update a case with evidence references and confidence/limitations.
7. Route to an authorised reviewer.
8. Record approve/reject/request-more-evidence decision.
9. Track action outcome and verified recovered value.
10. Report only reconciled, non-duplicated financial outcomes.

### Suggested bounded context services
- identity-access
- tenant-registry
- ingestion-connectors
- data-quality
- energy-reconciliation
- billing-reconciliation
- payment-reconciliation
- anomaly-intelligence
- agent-orchestration
- investigations
- recovery-workflow
- reporting
- licensing
- audit-evidence

A modular monolith is acceptable for the first PoV if boundaries and interfaces are explicit. Do not introduce microservices solely for appearance.

## 5. Canonical data domains

Minimum entities:
- Tenant, BusinessUnit, Region, ServiceArea
- CustomerAccount, Premise, Meter, MeterRegister, MeterRead, MeterEvent
- Feeder, Transformer, NetworkBoundary, EnergyFlow
- Tariff, TariffVersion, Bill, BillLine, Adjustment
- VendingTransaction, PaymentTransaction, Settlement, LedgerEntry
- Inspection, FieldVisit, OutageEvent
- SourceDataset, IngestionBatch, DataQualityIssue
- ReconciliationRun, Finding, EvidenceReference
- InvestigationCase, CaseAssignment, ReviewDecision
- RecoveryAction, RecoveryOutcome, Dispute
- ModelVersion, RuleVersion, AgentRun, Approval
- AuditEvent, LicenseEntitlement

Every operational record must include tenant_id and appropriate business_unit_id. Enforce isolation in the database, not only in application code. For PostgreSQL, use row-level security where applicable, server-verified tenant context, transaction-scoped context and fail-closed policies. Background jobs must carry and revalidate tenant scope.

## 6. Core calculations and controls

- Energy balance: compare measured input energy with downstream measured/billed energy only where boundaries, time windows, units and meter coverage are compatible.
- Technical loss estimate and commercial/unaccounted energy are separate measures. Do not label all unexplained energy as theft or non-technical loss.
- Revenue exposure is not the same as recoverable revenue. Report gross estimated exposure, confidence, disputed amount, approved recovery and cash actually received separately.
- Payment matching must support partial payments, split settlements, reversals, chargebacks, timing differences and duplicate references.
- All currency calculations use decimal arithmetic, explicit ISO currency, effective dates, exchange-rate source/time when conversion is required, and no implicit FX.
- Tariffs are versioned and effective-dated by jurisdiction/customer class.
- Reconciliation is idempotent and rerunnable; every run records input snapshot, formula/rule version, run time and result hash.
- Never double-count a customer, bill, payment or recovery across cases and reporting periods.

## 7. Security and privacy baseline

- TLS 1.2 minimum (TLS 1.3 preferred) in transit; strong encryption at rest with managed or customer-controlled keys.
- OIDC/OAuth2, MFA, least privilege, RBAC plus attribute-based restrictions, separation of duties and privileged-access review.
- Database-enforced tenant and business-unit isolation; automated negative isolation tests.
- Secrets in a secrets manager; no secrets or customer records in source control, logs or model prompts by default.
- Signed, tamper-evident audit events for data access, exports, model/rule changes, approvals and agent tool calls.
- Data minimisation, configurable residency/retention/deletion, legal hold and customer export controls.
- Secure SDLC: dependency and secret scanning, SAST, DAST, container scanning, SBOM, signed release artifacts and independent penetration testing before production certification.
- Prompt-injection defence: treat ingested documents and free text as untrusted data; never execute instructions contained in source records.
- Human approval for consequential financial/customer actions; four-eyes approval for configurable high-value thresholds.
- Incident response, backup/restore tests, disaster recovery objectives and customer notification procedures.

## 8. Deployment editions

### Customer-hosted
- Customer-controlled cloud, private cloud or on-premises deployment.
- Customer owns infrastructure, data plane, identity integration, backups and data residency choices.
- Signed offline-capable annual licence with bounded grace period and revocation/renewal process.
- No telemetry or data egress unless explicitly enabled and approved by the customer.

### CEPHAS-managed cloud
- Shared control plane with isolated tenant data planes or equivalent enforceable isolation.
- Dedicated tenant database/storage option for regulated customers.
- Region selection, tenant-specific encryption keys where supported, metering and transparent subprocessors.
- Per-tenant backup, export, deletion and incident processes.

Both editions use the same versioned API and domain model. Feature parity is tested; deployment-specific differences are documented.

## 9. Licensing design

Annual signed licence claims:
- issuer, product, edition, customer legal entity, tenant ID, deployment mode, approved environment fingerprint, enabled modules, user/record/asset/API limits, issue time, not-before, expiry, grace policy, licence ID and schema version.
- Sign claims using an asymmetric signing key held offline or in an HSM/KMS. Runtime contains public verification keys only.
- Validate signature, product, tenant, environment, validity and entitlements at startup and during privileged module operations.
- Support key rotation and key ID; reject unsigned, malformed, expired, wrong-tenant and tampered licences.
- Never use a shared secret embedded in the client as the sole trust anchor.
- Licence failure must not corrupt customer data; enter a documented read-only/grace mode where contractually configured.
- Record validation outcomes without logging the full licence token.

Commercial packaging: Foundation, Professional and Enterprise editions; modules and capacity limits configurable per contract. Do not hard-code Nigeria-only pricing, currency or tax assumptions.

## 10. Integration strategy and truthful claims

Potential integration categories, subject to discovery and customer authorisation:
- AMI/MDMS, meter data, vending, prepaid/postpaid billing
- SCADA / feeder and transformer telemetry
- GIS/network topology and asset registry
- CRM/customer information systems
- ERP/general ledger, bank settlement and payment gateways
- outage, maintenance, inspection and field-service systems

Initial PoV supports controlled synthetic data and documented CSV/API contracts. No production connector is claimed until built, tested against a named system/version, security-reviewed and accepted by the customer.

## 11. Quality and production gates

1. Data contracts, synthetic dataset, deterministic reconciliation tests and documented assumptions.
2. Tenant/business-unit isolation, identity, RBAC, audit and licence validation tests.
3. Working interactive PoV with end-to-end case lifecycle and reproducible demo reset.
4. Customer data mapping, data quality assessment and shadow-mode validation.
5. Model/rule validation: precision/recall, false-positive burden, calibration, drift and segment fairness where appropriate.
6. Security review, threat model, penetration test, backup/restore and operational runbooks.
7. Customer acceptance, deployment sign-off and production certification.

No gate is passed by a presentation or mock dashboard alone.

## 12. Success metrics

Track with explicit denominators and time windows:
- ingestion coverage and data freshness
- reconciliation coverage and unresolved mismatch rate
- precision and false-positive rate of reviewed findings
- median time from finding to triage and closure
- verified cash recovery (not merely estimated exposure)
- recovery yield against approved eligible cases
- duplicate-case and double-count prevention
- reviewer override rate and reason
- uptime, latency, security incidents and audit completeness

Targets are set after baseline measurement with the design partner; do not fabricate savings or accuracy claims.
