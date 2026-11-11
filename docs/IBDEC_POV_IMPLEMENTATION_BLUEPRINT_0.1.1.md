# CEPHAS AI PowerOps — IBDEC PoV Implementation Blueprint 0.1.1

**Workstream:** `pov/ibdec-readiness-audit`  
**Parent audit baseline:** `1671057a7633a50046af0722e7e2db2f61496662`  
**Blueprint status:** DESIGN BASELINE — NOT IMPLEMENTED OR CUSTOMER-APPROVED  
**Release intent:** Advisory-only IBDEC PoV, with reusable CEPHAS Enterprise ML and Feature Engineering foundations.

## 1. Executive decision

The IBDEC PoV is to be built as a controlled application of the CEPHAS Enterprise ML and Feature Engineering platform. Feature engineering, data quality, lineage, model governance, evaluation, monitoring and tenant-safe execution are platform capabilities—not ad hoc PowerOps scripts.

The PoV must not claim a trained or validated model until its dataset, training run, evaluation report, approval and deployed model artefact are traceable. The first usable milestone can deliver deterministic operational indicators and transparent feature pipelines before ML models are enabled.

This blueprint is a design and work breakdown only. It does not certify the current repository, authorise customer data access, connect to operational networks, or authorise customer installation.

## 2. Product and platform boundaries

### 2.1 PowerOps application layer

PowerOps owns utility-domain concepts and workflows:
- Feeder, transformer, substation and other approved asset records.
- Approved measurements and time-series observations.
- Outage/event records only where supplied and authorised.
- Operational indicators, asset/feeder views and reports.
- Engineer review, annotation, acknowledgement and disposition.
- Utility-specific dashboards, APIs and acceptance criteria.

### 2.2 CEPHAS Enterprise ML and Feature Engineering platform layer

The shared CEPHAS platform owns reusable capabilities:
- Ingestion contracts, schema validation and data-quality rules.
- Feature definitions, transformations, versioning and feature lineage.
- Point-in-time correct feature generation for training and inference.
- Dataset snapshots and reproducible training inputs.
- Training orchestration interfaces and experiment metadata.
- Time-aware evaluation, leakage checks and baseline comparisons.
- Model registry metadata, artefact integrity and publisher verification.
- Inference contracts, prediction provenance and uncertainty metadata.
- Drift/data-quality monitoring and model lifecycle governance.
- Tenant/business-unit isolation and auditable access to data, features and models.

PowerOps must call these through stable, versioned interfaces. Utility-specific features belong in a PowerOps domain package; generic transformations and governance controls belong in the shared platform.

### 2.3 Security boundary

All data, feature, dataset, model, prediction and audit queries must execute under a server-verified tenant and business-unit context. Isolation must be enforced at the database boundary where applicable (including PostgreSQL RLS), not merely by filtering in application code. Missing, invalid or conflicting context must fail closed. Background jobs must carry a verifiable, least-privilege execution context and must not bypass tenant isolation.

## 3. Target architecture

```text
Approved utility sources / customer-provided files
                 |
                 v
       Ingestion adapters and contracts
                 |
                 v
 Schema validation + quality + quarantine
                 |
                 v
 Tenant-scoped operational data store
                 |
          +------+------+
          |             |
          v             v
 Deterministic       Feature engineering
 domain metrics      (versioned definitions)
          |             |
          |             v
          |       Feature snapshots / lineage
          |             |
          |             v
          |       Governed training pipeline
          |             |
          |             v
          |       Evaluation and approval
          |             |
          |             v
          |       Signed model registry
          |             |
          +------+------+
                 |
                 v
     Advisory inference and explanations
                 |
                 v
 Dashboard / engineer review / reports
                 |
                 v
 Audit, monitoring, feedback and governance
```

The diagram is logical, not a claim that these components already exist in the repository.

## 4. Data and feature engineering contract

### 4.1 Initial PoV entities

Implement only entities covered by the signed data scope:
- `Asset`: stable asset ID, asset type, parent/location relationship, status and source.
- `Feeder`: stable feeder ID, source-system identity and approved topology references.
- `Measurement`: asset/feeder reference, metric name, value, unit, event timestamp, ingestion timestamp, quality code and source record ID.
- `Event`: event type, affected assets, start/end times, source and verification status.
- `DataQualityFinding`: rule ID, affected record/window, severity, evidence and disposition.
- `FeatureDefinition`: immutable/versioned feature ID, semantic meaning, input fields, transformation version, window, unit, null policy and owner.
- `FeatureValue`: entity key, feature version, event-time/as-of time, value, quality status and lineage reference.
- `DatasetSnapshot`: immutable query/specification, time range, source versions, row counts, exclusions and checksum.
- `ModelVersion`: model family, training snapshot, code/dependency versions, metrics, approval state and signed artefact digest.
- `Prediction`: model version, entity/time, output, uncertainty, explanation references, input feature snapshot and advisory status.
- `EngineerReview`: reviewer, decision, rationale, timestamp and linked prediction/indicator.

Every persisted record must include tenant and business-unit scope, where applicable, and provenance fields. Never silently substitute unknown units, timestamps, asset identifiers or quality states.

### 4.2 Data quality and time semantics

- Preserve source event time separately from ingestion/processing time.
- Normalise timestamps to UTC internally while retaining source timezone/offset metadata when supplied.
- Validate units and conversions explicitly; reject ambiguous or unsupported units.
- Detect duplicate, late, missing, out-of-range and stale observations.
- Quarantine invalid records with reasons; do not silently discard them.
- Record source, connector/file version, ingestion run and transformation version.
- Expose data freshness and coverage to users; do not present stale or incomplete measurements as current.
- Make corrections append-only or versioned so previous reports and model runs remain reproducible.

### 4.3 Feature engineering standards

Every feature must have a versioned definition with:
1. Business meaning and intended use.
2. Entity grain (asset, feeder, substation or time window).
3. Required source fields and units.
4. Transformation code/version and parameters.
5. Event-time window and as-of semantics.
6. Missing-data, outlier and quality handling.
7. Lineage back to source observations.
8. Tenant/BU enforcement and access classification.
9. Tests, owner and approval state.

Candidate initial features, subject to data availability and customer approval:
- Rolling mean, maximum, minimum and standard deviation of approved load measurements.
- Peak-to-baseline ratio and utilisation ratio only where rated capacity and unit semantics are verified.
- Load ramp/change rate over defined intervals.
- Measurement completeness, freshness and missingness.
- Repeated overload/threshold-exceedance counts using customer-approved thresholds.
- Outage/event frequency and duration only where event data is reliable.
- Asset age/maintenance recency only where authoritative fields are provided.

Thresholds, capacity ratings and operating limits must be customer-approved configuration—not invented constants. Deterministic indicators must expose formula, inputs, units, time window and data-quality status.

### 4.4 Point-in-time correctness and leakage prevention

Training features must use only information that would have been available at the prediction cutoff. Labels and future observations must never leak into feature computation. Splits must be chronological and grouped appropriately to avoid asset/time leakage. Every training and evaluation run must record cutoff rules, exclusions, feature versions and dataset snapshot identifiers.

## 5. ML capability scope and staged activation

ML is included in the platform design, but model activation is evidence-gated.

### Stage A — Data and deterministic baseline
- Build ingestion, validation, lineage, data-quality and feature computation.
- Establish transparent rule-based indicators and simple statistical baselines.
- Produce data coverage and quality reports.
- No claim of predictive AI maturity at this stage.

### Stage B — Offline model experiments
Only after sufficient approved historical data exists:
- Evaluate anomaly detection for unusual measurement/operating patterns.
- Evaluate short-horizon load forecasting where sampling and history support it.
- Evaluate asset-risk or maintenance-priority ranking only if reliable outcome labels and domain review exist.
- Compare against simple baselines; report performance by time period and relevant asset cohorts.
- Record uncertainty, limitations, false-positive/false-negative trade-offs and data gaps.
- No online operational reliance.

### Stage C — Shadow/advisory inference
- Run approved model versions in shadow or advisory mode.
- Show confidence/uncertainty and data-quality warnings.
- Require engineer review; capture accept/reject/override rationale.
- Monitor drift and performance; disable or roll back a model if guardrails fail.
- Predictions must never trigger control actions.

### Stage D — PoV acceptance
A model may be included in the customer PoV only if its dataset, training code, evaluation report, model artefact digest, approval and monitoring plan are available for independent review and the customer has approved the use case.

## 6. Model governance and supply-chain controls

- Treat model artefacts as untrusted until cryptographic signature and digest verification succeeds.
- Verify signatures and publisher trust before deserialisation or loading executable model formats.
- Prefer constrained, non-executable formats where practical.
- Pin training and inference dependencies; record environment and code commit.
- Separate model author, approver and deployer responsibilities.
- Maintain immutable model version and approval history.
- Reject unsigned, altered, expired, unapproved or wrong-tenant model artefacts.
- Keep training datasets and model artefacts tenant-scoped; no cross-customer training or data pooling without explicit contractual and technical authorisation.
- Do not expose raw sensitive source records through explanations or reports.

## 7. Advisory UX and operational safety

Every indicator or prediction shown to a user must state:
- Advisory status and that it is not an instruction or control command.
- Asset/feeder and time window.
- Data freshness, coverage and quality warnings.
- Feature/model version and generation timestamp.
- Explanation or contributing evidence appropriate to the method.
- Uncertainty/limitations where applicable.
- Engineer review status.

No SCADA, ADMS/DMS, protection relay, switching, dispatch or control write integration is in scope. Any future read-only integration requires separate threat modelling, customer approval, network segmentation and independent security review. Any control integration is explicitly outside this PoV.

## 8. Delivery work packages and gates

| Work package | Deliverable | Exit evidence |
|---|---|---|
| WP0 — Scope and architecture | Approved PoV scope, data authority, topology and module contracts | Customer-approved scope and architecture decision record |
| WP1 — Core security foundation | Server-verified identity, tenant/BU context, DB enforcement, RBAC and audit | Negative isolation tests, fail-closed tests and independent review |
| WP2 — Utility domain/data layer | Asset, feeder, measurement and event schemas/APIs | Domain tests, migration tests and data contract review |
| WP3 — Ingestion and quality | Approved file/API adapters, validation, quarantine and freshness | Reproducible ingestion tests and quality report |
| WP4 — Feature engineering | Versioned feature definitions, deterministic transforms and lineage | Unit/property tests, point-in-time and leakage tests |
| WP5 — Deterministic analytics | Transparent utilisation, peak, trend and rule-based indicators | Formula verification and engineer acceptance |
| WP6 — ML experimentation | Offline training/evaluation pipelines and baseline comparisons | Reproducible run, time-aware evaluation and independent model review |
| WP7 — Governed inference | Signed registry, verified loading, advisory predictions and monitoring | Tamper tests, approval workflow, uncertainty and rollback tests |
| WP8 — User workflows | Dashboard/API, annotations, reports and audit views | Role-based end-to-end acceptance |
| WP9 — Licence and packaging | Signed time-limited PoV licence, local validator, signed reproducible package | Expiry/tamper/revocation, install/rollback and backup/restore tests |
| WP10 — Customer readiness | Independent review and customer operational readiness | Exact-head CI, reviewer approval and written customer start authorisation |

Work packages may be developed in parallel only where dependencies and security boundaries are respected. WP1 is a prerequisite for handling real customer data.

## 9. Repository module boundaries (proposed)

The following is a proposed structure, not an assertion that these modules exist:

```text
src/powerops/
  api/
  application/
  domain/
    assets/
    feeders/
    measurements/
    events/
    analytics/
  infrastructure/
    persistence/
    ingestion/
    identity/
    licensing/
    audit/
  ml/
    contracts/
    features/
    datasets/
    evaluation/
    registry/
    inference/
    monitoring/
  reporting/
  config.py
  main.py

tests/
  unit/
  integration/
  security/
  tenancy/
  data_quality/
  feature_engineering/
  ml/
  e2e/
```

Keep shared CEPHAS ML/feature contracts independently versioned or packaged so other CEPHAS products can consume them without importing PowerOps utility-domain logic. Do not create a monolith of product-specific features inside the shared platform.

## 10. Required acceptance tests

At minimum, add automated tests for:
- Tenant A cannot read, mutate, aggregate, train on, infer from or export Tenant B data.
- Business unit boundaries are enforced within a tenant.
- Missing/forged tenant context fails closed, including asynchronous jobs.
- Feature values are reproducible for a fixed source snapshot and feature version.
- Point-in-time feature generation excludes future observations.
- Leakage tests detect label/future-field contamination.
- Invalid units, timestamps, duplicate records and stale observations are flagged.
- Quality degradation blocks or visibly degrades dependent features/predictions.
- Model signature is verified before any deserialisation/loading.
- Modified, unsigned, untrusted or wrong-scope model artefacts are rejected.
- Prediction records retain model, feature, dataset and source provenance.
- Advisory outputs cannot invoke control/dispatch/switching endpoints.
- Licence expiry, tamper, wrong-customer scope and revocation fail closed.
- Install, upgrade, rollback and backup/restore procedures are reproducible.

## 11. Decisions still required from IBDEC

No values should be guessed. Obtain written decisions for:
- Correct customer legal/operational name and authorised PoV sponsor.
- Approved assets, feeders, measurement types, units, sampling intervals and date range.
- Authoritative source systems and permitted export/API mechanisms.
- Data classification, residency, retention, masking and deletion rules.
- Approved user roles and engineer reviewers.
- Customer-approved operational thresholds and capacity ratings.
- PoV environment, network boundaries and installation ownership.
- Success criteria and acceptable false-positive/false-negative trade-offs.
- Whether historical labels/outcomes exist for any proposed ML use case.
- Named data owner, technical owner, security owner and acceptance authority.

## 12. Non-goals and release restrictions

This blueprint does not authorise:
- Live SCADA/ADMS/DMS write access or control actions.
- Production deployment or operational reliance on predictions.
- Training on customer data outside the agreed purpose.
- Cross-customer data pooling or model training.
- Unreviewed automatic model promotion.
- A weakened PoV-only identity, tenancy, audit or licensing path.
- Claims of production certification or mature predictive performance.

## 13. Immediate next engineering gate

**Gate B0 — Blueprint review and implementation decomposition.**

Required next actions:
1. Have the independent reviewer review this blueprint against the approved 0.1.1 implementation contract and security requirements.
2. Resolve any conflicts before implementation.
3. Create a sequenced implementation PR beginning with WP1 security/tenant foundation and WP2 data contracts; do not ingest real customer data until WP1 passes.
4. Build feature engineering and deterministic analytics with synthetic fixtures first.
5. Add offline ML experimentation only after feature correctness and data sufficiency gates pass.

**Current disposition: DESIGN BASELINE ONLY.** No runtime capability, ML model, customer data integration, licence validator or installation is represented as implemented by this document.
