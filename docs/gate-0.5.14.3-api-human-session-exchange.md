# Gate 0.5.14.3 — authenticated API exchange for human database sessions

## Implemented

- The OIDC API verifier now carries the configured, cryptographically verified issuer in `AuthenticatedPrincipal`; it is not read from request headers or body.
- The identity broker's `IssuedDatabaseSession` now returns the identity tuple it validated and provisioned: issuer, subject, tenant, business unit and finance-verifier entitlement, alongside the certificate, database role, expiry and session ID.
- Added `POST /api/v1/revenue/database-sessions`. It requires the API principal to have the `finance_verifier` role and a verified HTTPS issuer.
- The request accepts only a bounded broker-audience token and CSR. It does not accept tenant IDs, business-unit IDs, role names, DSNs, database passwords or private keys.
- The route delegates token verification, directory resolution, replay protection, CSR proof-of-possession and customer certificate issuance to the injected broker.
- Before returning certificate material, the route compares the broker-issued identity tuple against the independently authenticated API principal. A mismatch fails closed.
- Broker errors map to explicit HTTP outcomes: invalid assertion 401, directory authorization 403, replay 409 and unavailable customer dependencies 503.
- The API returns only the short-lived public certificate and metadata. The private key remains with the client that generated the CSR.
- The broker is initialized to `None` by default. No in-memory or demo broker is enabled in the application.

## Tests

- OIDC issuer propagation is asserted in the verifier tests.
- Broker-issued identity tuple and entitlement are asserted in broker tests.
- API tests cover successful exchange, identity mismatch, missing broker, replay conflict and missing finance-verifier role.
- Current-head CI remains the acceptance authority; this document does not claim a live customer identity provider, CA/HSM or mTLS integration.

## Outstanding integration and security work

- A customer-operated broker adapter, durable replay guard, production directory adapter and CA/HSM issuer must be injected by deployment configuration.
- The API route must be exposed only over the customer's approved HTTPS ingress and protected by the customer deployment's network controls. A dedicated broker mTLS listener and mutual TLS between the API and CA/HSM are not implemented here.
- The certificate connector's credential provider must securely materialize the issued certificate, private key and customer trust anchor for the same identity.
- Finance-sensitive repository writes still use the existing shared BU repository. They are not yet routed through `HumanDatabaseSession`; no shared-login fallback is permitted for the eventual strict maker/verifier path.
- Database-derived maker/verifier values, database-derived audit actors, PostgreSQL certificate-map deployment tests and end-to-end TLS integration remain later gates.
- Megabusters F-01 remains OPEN. No production certification or independent external review approval is claimed.
