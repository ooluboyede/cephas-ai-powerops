# PowerOps Revenue Assurance Gate 0.3.1 — Secret Management Foundation

## Objective

Define a provider-neutral, customer-controlled contract for retrieving runtime credentials. This gate does not select or claim integration with AWS Secrets Manager, Azure Key Vault, Google Secret Manager, HashiCorp Vault, or another managed provider.

## Security invariants

- Each deployed PowerOps service instance remains bound to one configured business-unit-scoped database identity and its own connection pool.
- A secret reference is deployment configuration, never a request parameter, tenant selector, or business-unit selector.
- Secret values are retrieved only by trusted server-side code. They must not be logged, returned by APIs, written to audit payloads, or persisted in PowerOps domain tables.
- Provider failures, missing values, denied access, and invalid versions fail closed. Do not silently fall back to inline credentials or another provider.
- Production provider access must use the customer's workload identity and least-privilege policy.
- Version identifiers and retrieval timestamps are metadata; they are not proof that a secret has been validated by PostgreSQL.
- Credential rotation is complete only after the replacement connection pool verifies the expected tenant and business-unit database identity.

## Adapter contract

The new src/powerops/secrets.py module defines:
- SecretProvider.get_secret(reference, version=None) -> SecretValue.
- SecretValue, which exposes a secret only through an explicit reveal() method and redacts repr() and str().
- Typed failures for not found, access denied, and unavailable/invalid versions.
- resolve_database_secret() for trusted server-side retrieval and non-empty validation.

Provider implementations must return a non-empty immutable version identifier for version-pinned providers. The local environment adapter returns the explicit marker "unversioned" and does not pretend to support immutable versions.

## Development adapter

EnvironmentSecretProvider supports only development/test configuration and references of the form env://UPPERCASE_VARIABLE. It is deliberately disabled when constructed with allow_insecure=False. Environment variables are not a production secret manager and do not provide version history, rotation audit, workload identity, or secret lifecycle guarantees.

## Configuration and deployment

No production secret provider is selected by this gate. Until the customer chooses a provider and approves its identity/access model, deployments must not claim managed-secret integration. The existing DATABASE_URL path remains the current connection configuration for earlier gates; Gate 0.3.1 introduces the adapter contract but does not yet switch application startup to it.

Before a production adapter is enabled, a subsequent implementation must:
1. Bind a secret reference to the static service deployment and its BU-scoped database identity.
2. Obtain provider credentials from the customer's workload identity, never a hard-coded API key.
3. Retrieve a specific secret version and validate its format without logging its value.
4. Pass the candidate credential to the existing replacement-pool verification path.
5. Record only non-secret reference/version/status metadata in the security audit channel.
6. Preserve the active pool if retrieval, validation, or replacement fails.

## Validation added

Unit tests cover environment-provider gating, supported reference syntax, missing values, version behavior, redacted representations, and timezone-aware retrieval metadata.

## Limitations and exit criteria

- No AWS/Azure/GCP/Vault adapter, workload-identity integration, rotation scheduler, secret revocation workflow, or provider audit integration is implemented.
- The environment adapter is development/test only.
- No test, lint, type-check, or PostgreSQL result is claimed until GitHub Actions can execute real job steps. Keep security workflows manual-dispatch only while Actions minutes are unavailable.
- Production adoption requires customer provider selection, adapter-specific security review, workload-identity validation, rotation/revocation tests, and independent security review.
