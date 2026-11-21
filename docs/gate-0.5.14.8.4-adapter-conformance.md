# Gate 0.5.14.8.4 — Credential Store Adapter Conformance

- Status: implementation and CI validation pending
- Branch: `security/revenue-assurance-gate-0.1`
- Scope: reusable application-level conformance assertions for every implementation of `HumanSessionCredentialStore`
- Out of scope: selecting a provider, production SDK, customer IAM, encryption proof, provider audit proof, CA issuance or live PostgreSQL TLS

## Objective

Make the existing credential-store protocol executable as a reusable acceptance contract. Every future customer-approved adapter must pass the same exact-session and immutable-record assertions before provider-specific acceptance begins.

## Required application-level behavior

1. An identical create retry for the same session UUID is idempotent.
2. Reusing a session UUID with any changed field raises `HumanSessionCredentialConflict`.
3. A conflict never mutates the original stored record.
4. Reads address one exact UUID; unknown UUIDs never fall back to another session.
5. Expired and revoked records are not retrievable.
6. Revocation is idempotent and scoped to exactly one session.
7. An independent, active session remains retrievable after another session is revoked.
8. A partial or failed write must never be exposed as a retrievable credential.
9. Provider outages, authorization failures, malformed responses and timeouts fail closed with secret-safe errors.

## Implementation

`tests/support/credential_store_conformance.py` supplies reusable assertions against the protocol. Each concrete adapter's test suite should instantiate an isolated adapter and invoke the helper using a valid-record factory. Provider-specific test suites must add concurrency/atomicity tests appropriate to their storage primitive and prove that failure injection cannot expose partial records.

## Additional provider-specific evidence (not proven by this helper)

- Customer workload identity and audience validation.
- Positive and negative IAM/policy tests, including denial of list, wildcard reads, policy administration and CA administration.
- Encryption-at-rest and customer-controlled key-management evidence.
- Provider audit records for create, read, renewal and revoke, with no secret payloads.
- Timeout, retry and malformed-provider-response behavior.
- Revocation of active PostgreSQL backends and measured revocation latency.
- Encrypted ephemeral key materialization and cleanup.
- Live non-production TLS handshake with `sslmode=verify-full`.

## Acceptance sequence

- Run the reusable conformance assertions against the test adapter.
- Add an adapter-specific suite only after the customer approves a provider and supplies its non-production environment.
- Run Ruff, Mypy, all Python tests and PostgreSQL 14–17 security/integration jobs.
- Obtain independent security review of the concrete adapter and customer evidence.
- Keep PR #21 draft and unmerged until all evidence is accepted.

## Explicit non-claims

Passing this helper proves only the tested application-level semantics of the adapter instance under test. It does not prove provider encryption, atomicity under concurrent distributed writers, IAM, audit, workload identity, CA security, live backend termination, customer integration or production readiness.
