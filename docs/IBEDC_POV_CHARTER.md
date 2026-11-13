# CEPHAS PowerOps — IBEDC Proof of Value Charter

**Programme:** IBEDC-first interactive Proof of Value  
**Audience:** IBEDC executive, network operations, engineering, ICT, commercial and regulatory stakeholders  
**Product posture:** advisory intelligence; customer-controlled deployment  
**Data posture:** synthetic fixtures first, followed by customer-approved data validation  
**Status:** proposed PoV scope; not a customer-approved engagement or production deployment

## 1. Purpose

Demonstrate how CEPHAS PowerOps can turn approved distribution-network data into explainable operational intelligence for feeder performance, transformer loading, outage patterns, energy reconciliation and demand planning.

The first presentation target is Ibadan Electricity Distribution Company (IBEDC). The product and evidence model must remain utility-agnostic so the same validated capabilities can later be configured for other DisCos.

## 2. PoV outcomes

1. Establish a repeatable, interactive command-centre demonstration using clearly labelled synthetic records.
2. Demonstrate feeder and transformer performance indicators with source lineage and transparent calculations.
3. Demonstrate outage history and restoration-duration analysis.
4. Demonstrate energy-input versus billed-energy reconciliation without automatically labelling the gap as technical or commercial loss.
5. Demonstrate demand and operational trend analysis only where the input history supports it.
6. Demonstrate evidence-grounded recommendations that remain advisory and require authorised human review.
7. Produce a data-readiness and integration-gap report after customer-approved sample data is received.

## 3. Demonstration scenarios

### Scenario A — Feeder performance
Select a feeder and inspect demand, rated capacity, loading percentage, recent outage count, source completeness and data freshness. A loading indicator is not a fault diagnosis.

### Scenario B — Transformer loading and prioritisation
Inspect transformer rated capacity, observed peak load, loading trend and risk band. Explain the inputs and threshold. The output is an investigation priority, not an automatic asset-health verdict.

### Scenario C — Outage analysis
Filter outage events by feeder, period and cause code. Show event count, duration distribution, restoration time and recurring patterns. Clearly separate supplied incident facts from derived summaries.

### Scenario D — Energy reconciliation
Compare energy input and billed energy for a defined period. Display the unreconciled gap and identify data completeness requirements. Do not equate the gap to recoverable revenue or non-technical loss without validated metering, billing, timing and network-boundary evidence.

### Scenario E — Executive intelligence assistant
Answer questions from the currently selected, permission-checked dataset. Responses must cite the records/metrics used, state uncertainty and distinguish measured values, derived features, model outputs and engineer-validated conclusions.

## 4. Evidence labels

Every chart, metric, alert and recommendation must carry one of these classifications:

- **Synthetic demonstration data** — generated fixture; never a customer measurement.
- **Measured** — directly supplied by an identified customer-approved source.
- **Derived feature** — deterministic calculation from identified records.
- **Model output** — output of a versioned and evaluated model.
- **Engineer-validated conclusion** — reviewed and accepted by an authorised utility professional.

The user interface must make the synthetic status visible, not merely place it in a footnote.

## 5. Success measures

No accuracy, savings, loss-reduction or restoration improvement is assumed in advance. The customer and CEPHAS will agree baselines and acceptance thresholds after data discovery.

- Data coverage, completeness, freshness and reconciliation.
- Feeder/transformer indicator reproducibility.
- Forecast error where sufficient time-series data exists.
- Detection precision, recall and false-positive rates where labels exist.
- Outage event and restoration-duration reconciliation.
- Analyst usefulness and acceptance of recommendations.
- Investigation time and evidence quality.
- Application stability, access control and audit evidence.

## 6. Data and integration boundary

The initial demonstration uses synthetic data only. It has no live SCADA, ADMS/DMS, GIS, AMI/MDMS, billing or outage-system connection.

The next stage accepts only data that IBEDC explicitly authorises for PoV validation, under an agreed data-processing, retention, access and security arrangement. The source system, extraction time, units, timezone, quality flags, owner and permitted use must be recorded for each dataset.

## 7. Operational safety

PowerOps is advisory-only. It must not issue switching, protection, dispatch, breaker, recloser or other operational control commands. It must not directly alter SCADA/ADMS/DMS systems. Recommendations are presented for human review and approval.

## 8. Release and acceptance boundary

A presentation build is not a production release. Before customer data is loaded, the applicable identity, database-enforced tenant/BU isolation, audit, data-retention, deployment and security gates must pass. Customer topology, scale, identity-provider and connection-pool decisions remain subject to the formal 0.1.1 Gate 0 approval process.

A PoV acceptance report must list tested scenarios, exact dataset versions, results, limitations, known defects, integration status and outstanding production gates.
