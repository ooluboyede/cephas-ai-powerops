# Feature engineering and ML delivery policy

Feature engineering and machine learning are first-class PowerOps platform capabilities, but they will be introduced in dependency order.

## Candidate feeder features

- Real and apparent power, current, voltage, and power factor where measured.
- Load factor and peak-to-average ratio over declared time windows.
- Rolling mean, median, quantiles, and variability.
- Voltage deviation and phase imbalance where phase-level data exists.
- Outage/fault frequency and duration from validated event records.
- Data completeness, freshness, and sensor-quality indicators.

## Candidate transformer features

- Loading ratio against a verified nameplate/rating basis.
- Peak loading and overload duration against utility-approved thresholds.
- Load trend and thermal indicators only where required inputs and validated thermal assumptions exist.
- Voltage/current imbalance and power-quality indicators where measurements support them.
- Fault, inspection, oil-test, and maintenance history where available and authorised.

## Model families (planned)

- Unsupervised/semi-supervised anomaly detection.
- Short-horizon feeder demand and transformer loading forecasts.
- Calibrated asset-risk and maintenance-priority models.

## Governance requirements

Each feature and model must have an owner, version, definition, unit, input lineage, time-window semantics, missing-data policy, training/evaluation dataset identity, metrics, approval state, and rollback path. Training/test splits must respect time and asset/tenant boundaries to prevent leakage.

No model may claim certainty that an asset will fail. Predictions must expose uncertainty, evidence, data freshness, and limitations, and remain subject to engineer review.

## Initial status

This repository foundation contains no feature computation pipeline, trained model, live utility data connector, or IBEDC integration. These will be implemented and tested in later pull requests.
