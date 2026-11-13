# IBEDC PoV — Synthetic Data Contract

**Status:** engineering contract for offline demonstration fixtures  
**Dataset class:** synthetic; no customer records or real network identifiers  
**Reference timezone:** Africa/Lagos (WAT, UTC+01:00)  
**Reference date for deterministic fixtures:** 2026-10-31

## 1. Required provenance

Every dataset and every record must carry the classification:

`SYNTHETIC_NOT_CUSTOMER_DATA`

Identifiers use a `DEMO-` prefix. The interface must display a persistent synthetic-data banner wherever these records are visible or exported. Synthetic records must never be silently mixed with customer-provided records.

## 2. Initial entities

| Entity | Key fields | Units / semantics |
|---|---|---|
| Feeder | feeder_id, name, nominal_voltage_kv, rated_capacity_mw, demand_mw, loading_pct, outage_count_30d | MW, kV, percentage; demonstration operating snapshot |
| Transformer | transformer_id, feeder_id, rated_capacity_kva, peak_load_kva, loading_pct, risk_level | kVA and percentage; loading indicator only |
| Outage | outage_id, feeder_id, started_at, restored_at, duration_minutes, cause_code | ISO-8601 timestamp with offset; event duration in minutes |
| Energy reconciliation | feeder_id, period_start, energy_input_mwh, billed_energy_mwh, unreconciled_gap_mwh | MWh; arithmetic difference, not a verified loss estimate |

## 3. Calculation rules

- Feeder loading percentage = demand MW / rated capacity MW × 100.
- Transformer loading percentage = peak load kVA / rated capacity kVA × 100.
- Transformer loading bands for the demonstration only: below 85% = normal loading band; 85–100% inclusive = elevated loading band; above 100% = high loading band.
- Unreconciled energy gap = energy input MWh − billed energy MWh.
- Outage duration = restored timestamp − start timestamp.

These bands are not IBEDC operating limits or protection settings. They must be replaced or approved by the utility before any operational use.

## 4. Explicit non-inferences

- Low utilisation is not proof of a fault.
- High loading is not proof of imminent failure.
- The energy reconciliation gap is not automatically technical loss, commercial loss, theft or recoverable revenue.
- An outage cause code is not a verified root-cause conclusion unless confirmed by an authorised source.
- A synthetic risk band is not a trained ML prediction.

## 5. Quality and validation requirements

- IDs are unique within their entity type and clearly synthetic.
- Rated capacities and energy inputs are positive.
- Demand, peak load and durations are non-negative.
- Timestamps include timezone offsets and restoration is after outage start.
- Derived percentages and energy gaps are reproducible from the displayed inputs.
- Missing, stale, estimated and invalid customer records must remain distinguishable during later validation.
- Dataset seed, generator version, reference time and export time must be retained for repeatability.

## 6. Customer-data transition

Customer-provided data is a separate data class and ingestion path. Before use, CEPHAS and IBEDC must agree source ownership, approved fields, units, time semantics, network hierarchy, quality codes, retention, access, deletion, permitted model-training use and validation owners. Synthetic fixtures are never relabelled as customer measurements.
