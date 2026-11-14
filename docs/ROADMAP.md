# Engineering roadmap

| Release | Scope | Exit gate |
|---|---|---|
| 0.1.0 | Repository foundation, CI, architecture and security baseline | CI green; design reviewed |
| 0.1.1 | Identity integration, tenant/BU context and PostgreSQL RLS | Adversarial isolation tests pass |
| 0.1.2 | Feeder, transformer, meter and time-series data contracts | Schema and validation tests pass |
| 0.2.0 | Versioned feature engineering and lineage | Deterministic feature tests pass |
| 0.2.1 | Data quality, feature registry and time-series pipelines | Missingness, freshness and leakage gates pass |
| 0.3.0 | Baseline anomaly and asset-risk models | Time-aware evaluation and explainability review |
| 0.3.1 | Load forecasting and maintenance prioritisation | Calibration and operational review |
| 0.4.0 | Feeder/transformer command-centre APIs and dashboards | Role, audit and usability tests |
| 0.4.1 | Maintenance workflow and engineer feedback | Workflow and approval tests |
| 0.5.0 | IBEDC PoV packaging and customer validation | Signed scope, security review and acceptance |

All integrations depend on IBEDC discovery, approved access, source-system capability, and data quality. Synthetic data may be used for development but must always be labelled synthetic.
