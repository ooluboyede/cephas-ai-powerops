# Gate 0.5.14.8.1 — Human Session Credential Store Contract Hardening

- Status: Implemented in source and contract tests; awaiting CI evidence
- Scope: Vendor-neutral storage boundary used by human PostgreSQL sessions
- Out of scope: concrete Vault/AWS/Azure adapter, customer infrastructure changes, CA provisioning, production certification

## Contract guarantees

The HumanSessionCredentialStore protocol is the only persistence boundary for short-lived human database certificates and private keys. Every implementation must satisfy:

1. **Exact immutable key:** session UUID is the sole lookup key. A record is never selected by actor, tenant, business unit, role, or a latest-session fallback.
2. **Create-only writes:** writes are atomic. An identical retry is idempotent; reuse of a UUID with any different record content raises HumanSessionCredentialConflict. Silent replacement is prohibited.
3. **Atomic visibility:** get_session cannot observe a partially written record.
4. **Scope binding:** issuer, subject, tenant, business unit, database role, exclusive finance entitlement, certificate, private key and expiry form one indivisible record.
5. **Expiry and revocation:** the store applies TTL no later than credential expiry. Expired or revoked records return no credential. Revocation blocks subsequent retrieval.
6. **Customer custody:** private keys are encrypted at rest under customer-controlled key management. The application workload has least-privilege access and cannot administer vault policies, mounts, namespaces or CA material.
7. **No secret leakage:** private keys and certificate payloads are excluded from logs, exception messages, telemetry, audit payloads and API responses.
8. **Fail closed:** outages, authorization failures and malformed store responses never fall back to shared credentials or another session.

## Runtime record validation

StoredHumanSessionCredential now validates its trust-boundary fields at construction:

- UUID session, tenant and business-unit identifiers
- HTTPS issuer and non-empty subject
- Exactly one of finance_operator or finance_verifier
- Database role restricted to pwr_[a-z0-9_]{1,40}
- PEM certificate and unencrypted PKCS8 private-key envelope markers
- Timezone-aware expiry

This validation is structural. The existing credential provider remains responsible for certificate parsing, certificate/key public-key equality, role-CN matching, expiry checks and secure ephemeral materialization.

## Adapter obligations

A future adapter must prove atomic create/idempotency/conflict behavior, exact UUID reads, cross-tenant and cross-business-unit denial, TTL enforcement, revocation, workload-identity expiry, outage behavior and secret-safe audit output against its actual provider.

No Vault SDK, endpoint, token, namespace, mount, PKI issuer or policy is assumed by this gate. The HashiCorp Vault ADR remains a proposed reference option pending customer approval.

## Acceptance evidence

- Unit tests reject malformed credential records and non-exclusive finance entitlements.
- Existing issuance and certificate materialization tests remain regression coverage.
- CI must pass configured Python quality/test jobs before this gate is accepted.
- The CI rerun is bound to the corrected branch head after the initial lint findings were fixed.
- Customer-provider integration and independent security review remain separate acceptance requirements.
