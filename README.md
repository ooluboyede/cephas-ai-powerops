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
