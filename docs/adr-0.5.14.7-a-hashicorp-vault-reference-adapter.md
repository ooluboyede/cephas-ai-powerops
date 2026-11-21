# ADR 0.5.14.7-A — Reference credential vault: HashiCorp Vault

- Status: Proposed reference integration; customer approval required
- Date: 2026-11-18
- Scope: PowerOps human database session credential storage and retrieval
- Decision owner: Customer security/platform owner with CEPHAS engineering

## Context

PowerOps already defines `HumanSessionCredentialStore` with exact-session `store_session` and `get_session` operations. The current `VaultBackedHumanPostgresCredentialProvider` validates the retrieved lease and materializes certificate/key files for the lifetime of a database connection. No concrete customer vault adapter is currently implemented.

The integration must preserve customer control of private keys, certificates, encryption keys, audit logs, access policies and revocation. The browser must never receive private key or certificate material. The application must fail closed if the vault, broker, identity validation or lease checks fail.

## Recommendation

Use HashiCorp Vault as the first reference adapter, provided the customer already operates it or approves its procurement and operational ownership. Keep the Python integration behind `HumanSessionCredentialStore`; do not leak Vault API types, paths, tokens or namespaces into domain/application services.

Prefer the customer's existing Vault deployment. For a greenfield deployment, evaluate Vault Enterprise where delegated namespace isolation, HSM auto-unseal, high availability, replication or enterprise governance are explicit requirements. Do not assume Enterprise is mandatory: Vault Community may be sufficient for a single-customer installation with simpler isolation and customer-owned operations. Edition, support lifecycle, licensing and hosting model require customer procurement approval.

## Proposed design

1. The PowerOps API workload authenticates to Vault using a short-lived workload identity supported by the customer's platform (for example Kubernetes auth, cloud workload identity, or AppRole only where the customer explicitly approves its lifecycle controls). Do not embed a long-lived root or operator token in application configuration.
2. The session broker validates the authenticated OIDC issuer, subject, tenant, business unit and exclusive finance entitlement before certificate issuance.
3. The broker requests a short-lived client-auth certificate from a customer-controlled issuing CA. Prefer an external offline root CA with a Vault-managed intermediate; do not move a customer's root private key into the application.
4. The customer vault adapter stores the exact session UUID as the immutable lookup key. Store the certificate, private key, issuer, subject, tenant, BU, database role, exclusive entitlement, expiry, certificate serial/fingerprint, and revocation state as one atomic record. The private key is encrypted at rest by Vault's storage encryption and protected by narrowly scoped policy.
5. The API returns only opaque session metadata. It never returns certificate or private-key bytes.
6. The existing provider retrieves by exact session UUID, revalidates every identity/scope/role/expiry field and certificate/key/CN match, then materializes the material into customer-approved encrypted ephemeral storage. Delete temporary files after connection closure.
7. Vault audit devices record workload access. Ensure sensitive request/response fields are not exposed in logs; audit configuration must be reviewed against PKI/secret payload behavior.
8. Revocation marks the lease unusable, prevents new retrieval/connection and triggers termination of existing PostgreSQL backends for that database role. Vault secret deletion alone does not terminate an already-open PostgreSQL connection.
9. Rotation issues a new certificate/session, proves it works, then revokes the old certificate and terminates sessions bound to the old role/lease according to customer policy.

## Isolation and policy model

- Use a dedicated namespace per customer environment where Vault Enterprise is available; otherwise use dedicated mounts and narrowly scoped policies with a documented isolation review.
- Separate production and non-production CA mounts, auth roles, policies and audit destinations.
- PowerOps workload identity may read/write only the exact customer-specific session path required by the adapter; it must not administer auth methods, policies, namespaces, mounts, CA issuers or audit devices.
- Separate platform/PKI administrators from application workload identities.
- No wildcard read/list access to other tenants' session records.
- Never allow the app to read CA private keys or issue arbitrary certificates.
- Enable and monitor Vault audit devices; protect audit logs from alteration and restrict access.

## Acceptance tests before customer sign-off

1. Exact session UUID read returns only the expected identity and certificate record.
2. Cross-tenant and cross-BU reads fail, including attempts to substitute a different UUID.
3. Workload identity expiry/revocation and Vault outage fail closed.
4. A secret record cannot be overwritten with a different actor or scope using an existing UUID.
5. Certificate/key mismatch, CN mismatch, invalid chain, wrong EKU, expired cert and revoked lease all fail.
6. A successful PostgreSQL `hostssl` + `cert` login with `sslmode=verify-full` maps to the expected `session_user` and database-derived actor.
7. Revocation prevents new sessions and terminates existing backends; rotation invalidates old credentials.
8. Temporary key material is removed on normal close and exception paths; the underlying ephemeral storage is customer-verified as encrypted.
9. Audit evidence contains request identity and outcome without private-key bytes, PEM, bearer tokens, secret payloads or DSNs.
10. Vault failover, restore, backup, audit-device failure and disaster-recovery procedures are exercised.

## Alternatives

- Customer's existing AWS Secrets Manager, Azure Key Vault or other enterprise secret manager: preferred over introducing Vault when it is already the customer's approved strategic service. Implement a separate adapter with the same interface.
- Vault Community: acceptable for a customer-controlled single-environment deployment after the customer accepts its operational and isolation model.
- HCP Vault Dedicated: evaluate only if customer policy permits managed control-plane hosting and the required data residency, connectivity and responsibility boundaries are satisfied.
- Local encrypted files or environment variables: rejected for production credential custody.

## Decision and implementation boundary

This ADR is a recommendation, not evidence of customer approval or an implemented adapter. Before coding the Vault adapter, obtain the customer's Vault endpoint/deployment model, auth method, namespace/mount path, policy owner, PKI issuer/role, audit destination, encrypted ephemeral storage specification and test environment. Do not create a production Vault namespace, policy, CA or secret on behalf of a customer without explicit authorization.

## References

- Vault PKI: https://developer.hashicorp.com/vault/docs/secrets/pki
- Vault PKI considerations: https://developer.hashicorp.com/vault/docs/secrets/pki/considerations
- Vault Enterprise namespaces: https://developer.hashicorp.com/vault/docs/enterprise/namespaces
- Vault editions: https://developer.hashicorp.com/vault/tutorials/get-started/available-editions
