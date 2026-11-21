# PowerOps PoV / Main Product Separation Contract

## Required product boundary

The IBEDC Revenue Assurance PoV is a standalone evaluation application, not the PowerOps enterprise product and not a production deployment mode of the enterprise application.

### PoV application

- Purpose: demonstrate the agreed IBEDC evaluation workflows with clearly labelled synthetic data, then customer-approved validation data.
- Owns: PoV UI, demo fixtures, demo reset/export behavior, PoV-only configuration and PoV deployment.
- Must not contain: production customer credentials, production secrets, production database access, production licence authority, or production operational integrations.
- Must display an unmistakable synthetic/demo boundary until customer data is explicitly approved and loaded under a separately governed evaluation agreement.
- Demo-only shortcuts must never be enabled in the main product through a runtime flag.

### Main PowerOps product

- Owns the production API, OIDC authentication, tenant/business-unit database isolation, audit, signed annual licensing, integrations, deployment hardening and release certification.
- Runs with customer-controlled infrastructure, customer-controlled data and a separately provisioned BU-scoped database identity and secret reference.
- Does not import the PoV HTML, demo fixtures, mock data services or PoV-only dependencies into its runtime package.

### Shared logic rule

Only deliberately reviewed, production-safe domain contracts or deterministic algorithms may be promoted from PoV to main product. Promotion requires code review, tests, data-lineage review and security review. The PoV does not become production merely because a demo feature is accepted.

## Current repository reality

The current PoV dashboard is in `demo/revenue-assurance/index.html` on the separate PoV proposal branch / PR #20, while the main product and security gates are in this repository's product branches. This provides branch and path separation but is not yet an independent GitHub repository. Do not describe the PoV as repository-isolated until it has been moved to a dedicated repository and independently deployed.

## Required next separation action

Create a dedicated repository named `cephas-ai-powerops-pov` (or another owner-approved name), move the PoV dashboard and demo-only assets there, give it its own CI, environment, data fixtures and deployment target, and leave the main product repository free of PoV runtime assets. Preserve PR #20 until the split is completed and reviewed; do not merge demo runtime code into the main product release line.
