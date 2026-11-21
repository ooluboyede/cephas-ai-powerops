# PowerOps Revenue Assurance Agent — Interactive PoV Plan

**Design partner:** IBEDC first; subsequent Nigerian DisCos and international utilities  
**Duration:** 90 days, subject to customer access and agreed calendar  
**Demo data:** Synthetic first, then customer-approved data validation  
**Operating mode:** Advisory; all consequential actions require authorised human approval

## PoV objective

Demonstrate an end-to-end revenue assurance workflow using synthetic, clearly labelled data, then validate data mappings and findings against a customer-approved sample. The PoV must demonstrate evidence traceability, not just charts.

## Demonstration journey

1. Select a utility, business unit, service area and reporting period.
2. Inspect ingestion health and data-quality exceptions.
3. Review energy, billing, vending and collection reconciliation.
4. Open ranked revenue-gap and meter/billing/payment anomaly findings.
5. Inspect evidence, calculation lineage, rule/model version and confidence limitations.
6. Create an investigation case, assign a reviewer and request more evidence.
7. Approve or reject a recommended action with reason and maker-checker control.
8. Record simulated or customer-validated recovery outcome.
9. View executive metrics that distinguish estimated exposure from approved and cash-recovered amounts.
10. Export an audit-ready evidence pack and reset the synthetic demo.

## Synthetic dataset

Include synthetic, deterministic records for:
- customer accounts, premises, meters and meter-to-account mappings
- feeder/transformer hierarchy and energy input readings
- meter reads and meter event signals
- tariffs and effective dates
- bills, bill lines, estimated reads and adjustments
- vending, payments, settlement and ledger entries
- inspection events and investigation outcomes

Seed scenarios:
- missing bill despite valid consumption
- flatline/zero consumption inconsistent with prior profile
- meter/account mapping mismatch
- duplicate or delayed payment settlement
- payment received but not allocated
- bill tariff version mismatch
- unexplained energy balance gap with incomplete boundary coverage
- valid exception that is cleared after evidence review
- false positive that a reviewer rejects
- partial recovery and reversal

Every synthetic record and dashboard must display a clear synthetic-data label. No real customer or employee data in demo seed files.

## 90-day sequence

### Days 1–15: Discovery and foundation
- Confirm customer use cases, business owners, source systems and data custodians.
- Agree definitions for energy supplied, billed energy, revenue, collection and loss.
- Confirm time boundaries, units, tariffs, account identifiers and data residency.
- Approve data dictionary, synthetic scenario catalogue and PoV acceptance criteria.
- Complete threat model and deployment choice.

### Days 16–35: Working synthetic PoV
- Implement ingestion, validation and canonical contracts.
- Implement deterministic billing/payment/energy reconciliation.
- Implement findings, case workflow, RBAC, audit and demo reset.
- Build executive command centre and evidence pack export.
- Demonstrate the complete journey above.

### Days 36–55: Customer data validation
- Receive minimum necessary, customer-approved, preferably pseudonymised extracts.
- Profile completeness, quality, coverage and mapping gaps.
- Run in shadow mode; do not change billing, meter or customer records.
- Compare outputs with utility expert labels and known cases.
- Record false positives, missed cases, uncertainty and data blockers.

### Days 56–75: Controlled operational evaluation
- Tune rules and thresholds with customer analysts.
- Run case assignment and human review workflow.
- Measure time-to-triage, evidence completeness, reviewer acceptance and verified outcomes.
- Test role separation, tenant boundaries, audit export and recovery controls.

### Days 76–90: Evaluation and next-step decision
- Produce results against agreed baseline and denominators.
- Present validated findings, limitations, data gaps and integration readiness.
- Deliver security/deployment assessment, runbooks and production backlog.
- Obtain customer acceptance or document remediation items.

## Minimum acceptance criteria

- Reproducible synthetic demo with reset and no hidden manual data edits.
- Source-to-finding provenance for every displayed exception.
- Deterministic reconciliation results repeat exactly for the same input snapshot and formula version.
- Estimated exposure, approved recovery and cash received are separate measures.
- Human approval and maker-checker controls for consequential actions.
- Database-enforced tenant and business-unit isolation, including background jobs.
- Complete audit history for ingestion, finding, assignment, review, approval, export and outcome.
- Negative tests prove users cannot read or mutate another tenant/business unit's records.
- No unapproved outbound data transfer or operational control command.
- Customer-data results clearly state coverage, quality, limitations and validation status.

## Required customer data (subject to approval)

Minimum useful extracts: account/customer reference (pseudonymised where possible), meter reference, meter reads/intervals, bills and tariff versions, vending transactions, payment receipts/settlements, ledger allocations, feeder/transformer mapping and relevant inspection events. Agree exact fields, purpose, retention, transfer channel and deletion before receipt.

## PoV exclusions

- No autonomous disconnection, reconnection, meter configuration or firmware commands.
- No autonomous bill adjustment, refund, journal posting or customer penalty.
- No definitive theft/fraud accusation from an anomaly score.
- No production integration claim before system-specific build, test and customer acceptance.
- No guaranteed recovery amount or accuracy percentage before measured validation.

## Deliverables

- Working interactive synthetic PoV.
- Data dictionary and source mapping templates.
- Reconciliation and anomaly scenario catalogue.
- Security and deployment architecture.
- 90-day PoV plan and acceptance report.
- Evidence pack and executive dashboard.
- Commercial proposal and production rollout roadmap.
