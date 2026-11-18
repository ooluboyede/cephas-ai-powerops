# Gate 0.5.13 — Identity Broker Core Proof of Concept

**Status:** Isolated broker core and tests authored; execution and customer integration are pending.  
**PR:** #21 — keep open, draft and unmerged.  
**Finding:** F-01 remains OPEN.  
**Scope:** A broker service core only. This is not a deployed identity broker and does not establish database-authenticated human identity end to end.

## 1. What was added

### `src/powerops/identity_broker.py`

A broker core separated from the PowerOps API and existing BU-shared PostgreSQL pool:

- `OidcBrokerTokenVerifier` validates customer RS256 tokens against a configured HTTPS JWKS endpoint, exact issuer and broker-specific audience.
- Requires a non-empty immutable subject, tenant and BU UUID claims, finance-verifier entitlement, `jti`, issue/expiry timestamps, customer-approved `acr`, MFA `amr`, and recent `auth_time`.
- Rejects expired/invalid tokens, unsupported algorithm, wrong issuer/audience, excessive token age/lifetime, stale or future step-up time, malformed scope and missing MFA assurance.
- `IdentityDirectory` resolves a pre-provisioned human DB principal by issuer + subject + tenant + BU. Role names are never accepted from the API or CSR.
- `AtomicReplayGuard` is an explicit dependency contract. The broker fails closed if replay storage is unavailable or a token ID was already consumed.
- CSR parsing verifies proof of possession, caps CSR size, permits RSA keys of at least 3072 bits or P-256/P-384 EC keys, and fingerprints the public key.
- The broker selects the database role only from the trusted customer directory and bounds certificate lifetime by both token expiry and the configured maximum (at most five minutes).
- `CustomerCertificateIssuer` is an injected customer-controlled CA/HSM boundary. The broker requires the adapter to verify the issued certificate signature/chain against customer trust anchors and locally checks public-key match, role CN and validity window.
- Directory, replay-store, signing and certificate-validation failures fail closed with typed dependency errors.

### `tests/test_identity_broker.py`

Seven tests are authored for:
1. A short-lived certificate bound to the customer-directory role.
2. Replayed token identifier rejection.
3. Finance-verifier entitlement enforcement.
4. Missing customer directory identity rejection.
5. Invalid CSR rejection.
6. CSR subject cannot choose a privileged database role.
7. RS256 signature, issuer, audience and step-up/MFA claim checks.

The test CA and in-memory replay guard are explicitly test-only fixtures. They are not production adapters.

## 2. What is not implemented

The following remain required before this can be called an operational broker:

- An HTTPS broker endpoint with workload mTLS or equivalent customer workload identity.
- A production identity-directory adapter and lifecycle synchronization from the customer's IdP.
- A durable, atomic replay ledger shared by broker instances, with retention and concurrency tests.
- A production CA/HSM signing and chain-validation adapter, key rotation, revocation and certificate serial ledger.
- Customer-configured PostgreSQL client-certificate authentication and certificate-to-role mapping.
- Pre-provisioning of distinct human LOGIN roles and protected role-OID-to-issuer/subject/tenant/BU/entitlement mappings.
- A database actor resolver based on authenticated `session_user`, and recorder/verifier/audit writes derived from that resolver.
- Per-human connection lifecycle or an identity-aware proxy; the existing shared BU pool is not safe for human maker-checker identity.
- Revocation fencing and termination of already-open database sessions.
- Customer-specific MFA/ACR policy, token issuer and audience configuration.

No migration was added and no existing API route or database behavior was changed. The broker core is not wired into production request processing.

## 3. Security caveats and acceptance

- The test-only replay guard uses process memory and is not concurrency-safe across processes; it proves only the broker's dependency contract, not production replay protection.
- The test-only CA is disposable. It does not authorize customer deployment.
- A client certificate proves possession of its private key, not a person's physical presence. Customer MFA/step-up and key custody remain required.
- The broker core's tests use a stub token verifier for orchestration paths and a patched JWKS client for cryptographic JWT validation. They do not replace a live customer IdP integration test.
- The database has not yet been configured to trust certificates from this broker, and the shared BU connection pool remains unchanged.
- No CI workflow run or test execution is claimed for this gate. The exact current SHA must be validated by Ruff, Mypy, the new broker tests, and the existing PostgreSQL 14–17 matrix before acceptance.

## 4. Acceptance required to close F-01

1. Run the broker tests and all existing CI on the exact implementation SHA with retained logs.
2. Test a production-like broker with customer OIDC, directory, durable replay storage and customer CA/HSM adapters.
3. Prove two human users in the same BU authenticate as distinct PostgreSQL `session_user` principals using actual client certificates.
4. Prove direct SQL cannot spoof `verifier_subject`, change a GUC to impersonate, switch to another human role, or cross tenant/BU.
5. Prove database recorder, verifier and audit actors are derived from the protected database mapping; the maker cannot verify their own outcome and an entitled checker can.
6. Prove expiry, revocation, broker outage, stale pooled sessions, CA rotation and PostgreSQL 14–17 behavior.
7. Obtain fresh independent Megabusters review against the exact implementation SHA.

## 5. Current disposition

| Control | Status |
|---|---|
| Broker core interfaces and orchestration | Authored; unexecuted |
| OIDC verifier | Authored; no live customer IdP |
| CSR validation and role selection | Authored; unexecuted |
| Production replay guard | Not implemented |
| Production CA/HSM adapter | Not implemented |
| Broker mTLS endpoint | Not implemented |
| PostgreSQL certificate authentication | Not configured |
| Database actor mapping/resolver | Not implemented |
| Human-aware connection pool/proxy | Not implemented |
| F-01 | **OPEN — merge and financial PoV blocker** |
| F-02 | Code/test correction authored; real PostgreSQL execution still pending |
| Independent approval | Not granted |

**Governance:** Keep PR #21 open, draft and unmerged. This gate is a foundation for a customer-specific proof of concept, not production certification or authorization for financial operations.
