# PowerOps architecture

## Product boundary

PowerOps is an advisory distribution-network intelligence platform. Its first operational focus is:
- Feeder performance and capacity utilisation.
- Transformer loading and asset condition.
- Anomaly detection and explainable risk indicators.
- Maintenance prioritisation and work-planning support.
- A network intelligence command centre.

The initial release must not issue SCADA/ADMS switching, protection, dispatch, or control commands.

## Logical layers

1. **Integration and ingestion** — approved SCADA/DMS, AMI/MDMS, meter, GIS, asset-register, outage, inspection, and work-order feeds. Every connector is a separately scoped integration; none is assumed to exist.
2. **Data quality and lineage** — source identity, event time, ingestion time, units, quality flags, freshness, and provenance.
3. **Operational domain** — utilities, tenants, business units, feeders, transformers, meters, observations, outages, inspections, and maintenance events.
4. **Feature engineering** — deterministic, versioned transformations with explicit windows, units, missing-data behavior, and lineage.
5. **ML intelligence** — anomaly, load forecast, asset-risk, and maintenance-priority models, introduced only after data validation and baseline evaluation.
6. **API and user experience** — role-scoped operational views, explanations, review and feedback.
7. **Governance and security** — tenant isolation, audit, model registry, signed artifacts, access control, and customer-controlled deployment.

## Evidence semantics

Every displayed indicator must be labelled as one of:
- **Measured** — directly supplied by an identified source.
- **Derived feature** — deterministic calculation from identified measurements.
- **Model output** — probabilistic or scored output from a versioned model.
- **Engineer-validated conclusion** — reviewed and accepted by an authorised utility professional.

Low utilisation is not, by itself, evidence of a fault. Under-utilisation, overload, data-quality anomalies, topology changes, and asset-health risk are separate conditions and must be modelled and explained separately.

## Deployment

Target deployment is customer-controlled and customer-hosted. Container packaging, database operations, key management, backup/restore, monitoring, and signed annual licensing will be delivered in subsequent gated phases.
