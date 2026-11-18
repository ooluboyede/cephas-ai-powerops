# Gate 0.5.14.3 — server-side human database-session exchange

## Implemented

- The OIDC API verifier carries the cryptographically verified issuer in `AuthenticatedPrincipal`; it is never read from request headers or body.
- The identity broker's `IssuedDatabaseSession` returns the validated identity tuple: issuer, subject, tenant, business unit and finance-verifier entitlement, alongside certificate, database role, expiry and session ID.
- Added `HumanSessionIssuer`. The API server generates an EC P-256 private key and CSR itself; it sends only the CSR and the short-lived broker token to the injected customer broker.
- The broker validates the token, assurance level, directory mapping, replay state and CSR proof-of-possession, then returns a customer-signed certificate.
- The issuer compares the broker-issued identity tuple against the independently verified API principal and validates the database role and certificate lifetime before storage.
- The certificate and private key are passed to an injected customer-controlled credential store. The store contract requires encryption at rest and expiry enforcement. No default or in-memory credential store is enabled.
- `POST /api/v1/revenue/database-sessions` accepts only a bounded broker token and requires the finance-verifier role plus a verified HTTPS issuer.
- The API response contains only a non-secret lease: session ID, database role and expiry. It does not return the certificate or private key. The private key is never sent to the browser.
- Broker errors map to explicit HTTP outcomes: invalid assertion 401, directory authorization 403, replay 409 and unavailable customer dependencies 503.
- The application defaults `human_session_issuer` to `None`; the endpoint fails closed until the customer deploys and injects its broker and credential-store adapters.

## Tests

- OIDC issuer propagation is asserted in verifier tests.
- Broker identity tuple and entitlement are asserted in broker tests.
- Session-issuer tests validate CSR creation, server-side key retention, identity mismatch rejection and credential-store failure.
- API tests cover non-secret lease response, missing issuer adapter, replay conflict and finance-verifier authorization.
- The workflow runs these focused tests and the full suite across PostgreSQL 14–17.

## Outstanding integration and security work

- A customer-operated broker adapter, durable replay guard, production directory adapter and CA/HSM issuer must be injected by deployment configuration.
- The credential store must be implemented using customer-controlled secure storage, with atomic writes, encryption at rest, strict access controls, TTL deletion and audit.
- The credential provider must retrieve the matching session certificate and materialize the corresponding private key only for the bounded PostgreSQL connection. The private key must never be exposed to the browser or application logs.
- PostgreSQL `hostssl` certificate authentication and certificate-map deployment tests, including a live TLS handshake, remain outstanding.
- Finance-sensitive repository writes are still on the shared BU repository and are not yet routed through `HumanDatabaseSession`. No shared-login fallback is permitted for strict maker/verifier operations.
- Database-derived maker/verifier values and database-derived audit actors remain later gates.
- Megabusters F-01 remains OPEN. No production certification or independent external reviewer approval is claimed.
