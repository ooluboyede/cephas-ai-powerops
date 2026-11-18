# Gate 0.5.14.7 — customer certificate-authenticated PostgreSQL integration

## Purpose and boundary

This gate is the deployment-side acceptance contract for connecting the existing exact-session credential flow to a customer's CA/broker, encrypted credential store and PostgreSQL cluster. It does not select a vault, CA, HSM, broker protocol or cloud vendor on the customer's behalf.

The application-side interfaces already exist:
- `HumanSessionBroker.issue_session(token, csr_pem)`
- `HumanSessionCredentialStore.store_session(...)` / `get_session(session_id)`
- `VaultBackedHumanPostgresCredentialProvider`
- `PsycopgHumanSessionConnector`, which enforces TLS `verify-full`, a trusted database role, certificate/key matching, CN-to-role matching, a maximum five-minute lease and connection-lifetime key-file cleanup.

A production adapter is not implemented until the customer selects and supplies its supported vault/CA/broker interfaces. Do not substitute a local plaintext file store or environment-variable private key for a production vault.

## Customer decisions and prerequisites

Before enabling the integration, the customer security/database owners must provide and approve:
1. Secret-vault product/API, workload identity method, immutable secret versioning, encryption-at-rest policy, access audit, TTL deletion and revocation semantics.
2. CA/HSM and certificate profile, including client-auth EKU, trusted issuer chain, maximum five-minute validity, and role-bound CN.
3. Broker authentication and authorization contract, including how it validates the signed-in OIDC issuer/subject, tenant, BU and exclusive finance entitlement before signing a CSR.
4. PostgreSQL endpoint, database, DNS name present in the server certificate SAN, client-CA trust, approved network source and customer-managed encrypted ephemeral directory.
5. Customer change owner and a non-production database with a provisioned maker and a separate verifier role.

## PostgreSQL server configuration pattern

The DBA must adapt and review this pattern for the installed PostgreSQL version and local role/network policy. Keep the server certificate SAN aligned with the DNS hostname used by the application.

In `postgresql.conf`:
```conf
ssl = on
ssl_cert_file = 'server.crt'
ssl_key_file = 'server.key'
ssl_ca_file = 'approved-client-ca-chain.crt'
```

In `pg_hba.conf`, add a narrowly scoped rule before broader matching rules:
```conf
# Replace database, role group and CIDR with customer-approved values.
hostssl  powerops_db  +powerops_human_session_logins  10.20.30.0/24  cert
```

The certificate CN must equal the broker-assigned PostgreSQL login name because the application independently enforces that equality. Do not permit password, trust, host (non-TLS), `SET ROLE`, or shared-pool fallback for these human-session logins. Keep runtime roles non-superuser, non-owner and without membership in privileged roles. Provision distinct maker and verifier logins and retain the database-side role-OID-to-human mapping.

After configuration changes, reload PostgreSQL and inspect the effective HBA ordering. Do not expose the database publicly.

## Required customer vault/broker adapter properties

- Vault writes are atomic and idempotent on the exact session UUID; duplicate IDs cannot overwrite a different identity.
- Private keys are encrypted at rest under a customer-managed key and never logged, returned to the browser, placed in API responses or included in exception text.
- Reads require the PowerOps workload identity and exact session UUID; the adapter verifies lease expiry and active/revoked state on every read.
- Vault access is audited without recording secret material.
- TTL deletion is enforced by the vault, not only by application cleanup.
- Broker rejects expired/replayed/incorrectly scoped tokens and enforces issuer, subject, tenant, BU and exactly one finance entitlement.
- Certificate is short-lived (at most 300 seconds), client-auth capable, and has CN equal to the exact pre-provisioned DB login.
- Revocation blocks new issuance and vault reads immediately; the customer runbook terminates existing PostgreSQL backends for the revoked role. Marking a role NOLOGIN alone does not terminate an already-open session.
- Rotation issues a new session/certificate and retires the previous lease without overlapping identity or privilege.

## Executable TLS acceptance check

Run the companion `tests/postgresql/gate0_5_14_7_tls.py` from an approved customer test runner with the environment variables documented in that file. It opens one physical connection using the customer client certificate and performs read-only checks:
- TLS is active for the current backend.
- `session_user` and `current_user` are the expected broker-assigned role and are identical.
- The database resolver returns the expected issuer/subject, tenant, BU and exclusive maker/verifier entitlement.
- The database session is not using a caller-controlled identity GUC.

The script intentionally does not provision roles, change HBA settings, revoke sessions, or write business data. Run it separately with a maker and verifier certificate. Retain sanitized stdout, database version, certificate serial/fingerprint, CA chain identifier and test timestamps in the customer's change record; never retain private keys or raw connection strings.

## Additional required integration tests

The customer environment acceptance record must separately demonstrate:
1. Wrong server hostname/CA, expired client certificate, mismatched certificate/key and mismatched CN are rejected.
2. Wrong issuer/subject/tenant/BU/finance entitlement is rejected before business SQL.
3. Vault unavailable, broker unavailable, expired lease, revoked lease and missing secret fail closed.
4. Revocation prevents new sessions and terminates all existing sessions for the revoked database role.
5. Rotation succeeds with the new certificate and old certificate/lease can no longer establish a session.
6. PostgreSQL restart/failover and vault/broker dependency outage do not trigger password or shared-pool fallback.
7. Audit records contain no tokens, private keys, PEM blocks, DSNs or other secret values.

## Acceptance evidence and current status

This gate is **not accepted** until a named customer environment has supplied the adapters and a real TLS certificate-authenticated connection succeeds. The repository CI password connector is test-only and is not evidence for this gate. The companion test script is an acceptance harness, not proof that a customer CA, vault, broker or PostgreSQL cluster has been integrated.

No customer vault adapter, production CA/HSM adapter, live broker transport, customer HBA configuration, real TLS handshake, rotation/revocation evidence or independent security approval is claimed by this document. PR #21 remains draft and unmerged; no production certification is implied.
