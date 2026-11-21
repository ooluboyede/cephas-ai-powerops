# Gate 0.5.14.6 — bind finance requests to exact issued DB session leases

## Implemented

- Added a mandatory `session_id` to `HumanSessionPrincipal` and `HumanPostgresCredentials`.
- The server-side credential-store contract now supports retrieving one exact session lease by UUID.
- Added `VaultBackedHumanPostgresCredentialProvider`. It retrieves the exact session from the injected customer vault, checks the full human identity and finance entitlements, and rejects expired or mismatched leases.
- The provider materializes the client certificate and private key into a customer-configured owner-only temporary directory. The private key file is mode 0600; the temporary directory is mode 0700 and must be owned by the service account and mounted on encrypted ephemeral storage.
- `PsycopgHumanSessionConnector.connect()` is now a context manager. It keeps the credential materialization alive only while the physical PostgreSQL connection is open, then closes the connection and removes the temporary key files.
- The connector checks that the credential-store session ID equals the requested human session ID in addition to issuer, subject, tenant, business unit and finance entitlements.
- Recovery maker and verifier API requests now require the opaque `X-CEPHAS-DB-Session` header. The ID is passed through the human repository into the credential provider; a bearer token alone cannot select another user's database session.
- Added tests for session-ID mismatch, exact vault lookup, secure temporary-directory ownership and permissions, file cleanup, and missing API session headers.

## Deliberate limitations

- The customer credential-store implementation remains an injected interface. It must encrypt private keys at rest, enforce TTL deletion, audit reads/writes and return secrets only to the authorized service identity.
- The configured temporary directory must be an encrypted ephemeral mount managed by the customer. The code verifies owner and permissions but cannot prove the underlying filesystem is tmpfs or encrypted.
- The CI PostgreSQL repository adapter remains password-based and test-only. Live certificate authentication against customer PostgreSQL `hostssl` and certificate maps is still a separate acceptance gate.
- No production certification or external reviewer approval is claimed.
