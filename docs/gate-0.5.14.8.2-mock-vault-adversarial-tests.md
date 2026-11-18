# Gate 0.5.14.8.2 — Mock Vault Adapter and Adversarial Contract Tests

- Status: Implementation in progress; CI acceptance pending
- Scope: Deterministic test-only adapter exercising the vendor-neutral credential-store contract
- Out of scope: production Vault client, customer endpoints/tokens, CA integration, PostgreSQL live TLS, production certification

## Test-only mock adapter

The mock adapter is deliberately confined to the test suite. It models the contract's critical storage semantics without pretending to provide encryption at rest, real workload identity, provider audit logs or production availability.

It must implement:

- Atomic create-only storage keyed by session UUID
- Idempotent retries for identical records
- Conflict on any changed field for an existing UUID
- Exact UUID reads, with no actor/tenant/BU fallback
- Expiry-aware reads and idempotent exact-session revocation
- Fail-closed simulated provider outage using a safe exception
- No secret values in error text

## Adversarial acceptance tests

1. Same UUID + identical complete credential record: accepted idempotently.
2. Same UUID + changed actor, scope, role, entitlement, certificate, private key or expiry: rejected without altering the original.
3. Unknown UUID: returns no record even if another session for the same actor or tenant exists.
4. Expired UUID: returns no record.
5. Revoked UUID: returns no record; revoking one UUID does not affect another.
6. Simulated provider outage: raises a safe unavailable exception and never returns a fallback credential.
7. Error representation: does not include certificate or private-key contents.

## Security boundary

These tests validate application-level contract behavior only. A production adapter still requires provider-specific concurrency/atomicity tests, IAM policy review, encryption-at-rest evidence, audit verification, workload identity tests, revocation behavior, independent review and customer acceptance.
