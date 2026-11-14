# CEPHAS AI PowerOps

Enterprise distribution-network intelligence for electricity distribution utilities.

PowerOps is designed to provide advisory intelligence for feeder and transformer performance, asset condition, anomaly detection, load forecasting, and maintenance prioritisation. It distinguishes source measurements, engineered features, model outputs, and engineer-validated conclusions.

## Deployment model

Target deployment is customer-controlled and customer-hosted with annual signed CEPHAS licensing. Integrations require customer discovery and approved access.

## Safety boundary

The initial product is advisory only. It does not issue switching, protection, dispatch, or other operational control commands.

## Current status

This repository is at the 0.1.0 foundation stage. No production utility integrations, trained ML models, or production certification are claimed. See `docs/ROADMAP.md` for gated delivery stages.

## Authentication configuration

Revenue Assurance API access requires a configured OIDC provider. Install the pinned verifier
dependency with `uv pip install -r requirements-auth.txt`, then set `OIDC_ISSUER`,
`OIDC_AUDIENCE` and `OIDC_JWKS_URL`. All three settings are required together. The
provider's RS256 access tokens must carry the documented tenant, business-unit and roles claims.
See `docs/revenue-assurance/API_CONTRACTS.md` for the claim contract.


## Revenue Assurance Gate 0.2

Gate 0.2 adds a bounded PostgreSQL pool isolated to one BU-scoped database login per application service instance, per-checkout authenticated-scope verification, transactional rollback/commit on pool return, controlled credential-pool replacement after scope verification, and graceful pool shutdown. See [Gate 0.2 implementation and limitations](docs/revenue-assurance-gate-0.2.md).

Configure `DATABASE_POOL_MIN_SIZE`, `DATABASE_POOL_MAX_SIZE` and `DATABASE_POOL_TIMEOUT_SECONDS` as needed. Do not share a pool across business units. Secret-manager SDK integration and automated rotation scheduling remain future work; the repository exposes a validated credential-rotation operation for a deployment-owned secret provider.


## Revenue Assurance Gate 0.3.1

Gate 0.3.1 introduces a provider-neutral secret retrieval contract and a redacted secret value type, with a development/test-only environment adapter. No production secret-manager provider is selected or integrated yet. See [Gate 0.3.1 implementation and limitations](docs/revenue-assurance-gate-0.3.1.md).
