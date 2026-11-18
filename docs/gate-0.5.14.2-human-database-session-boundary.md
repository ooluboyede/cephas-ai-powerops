# PowerOps Gate 0.5.14.2 — per-human database session boundary

## Objective

Establish an executable application-side boundary that accepts database access only after PostgreSQL proves the connection belongs to the exact verified human principal. This is the first integration increment after the protected role-OID mapping in Gate 0.5.14.1.

## Implemented

- Added `HumanSessionPrincipal`, a typed identity envelope containing the verified issuer, subject, tenant, business unit and finance-verifier entitlement.
- Added the customer-owned `HumanSessionConnector` contract. It must open a fresh PostgreSQL connection authenticated with the short-lived certificate for that human; it must not use the shared BU pool or multiplex human identities.
- Added `HumanDatabaseSession`, which resolves the actor through `powerops_security.resolve_authenticated_human_actor()` before yielding the connection to application SQL.
- The database check compares issuer+subject, tenant, business unit and finance-verifier entitlement. It also requires `session_user = current_user`, rejecting a session that has executed `SET ROLE`.
- A failed identity check raises before application SQL and rolls back the transaction. The connector context owns connection closure.
- Added adversarial unit tests for role switching, wrong tenant, wrong business unit, wrong subject, missing mapping and verifier-entitlement mismatch.

## Deliberate limitations

- The connector is an interface, not a production certificate-authentication adapter.
- No HTTP/mTLS broker endpoint, customer CA/HSM integration, durable replay store, CSR/private-key lifecycle, PostgreSQL `hostssl`/certificate mapping configuration, or deployment trust-anchor setup is included in this gate.
- The existing shared BU pool and repository are not yet switched to this boundary. Therefore Gate 0.5.14.2 does not close F-01 and must not be described as end-to-end per-human authentication.
- The next integration step must wire the broker-issued certificate to the connector, propagate the verified issuer from API authentication, and route finance-sensitive repository operations through this boundary with no shared-login fallback.

## Acceptance

The focused tests exercise the boundary with a fake connector. Full acceptance still requires the workflow to run on the exact commit and real PostgreSQL 14–17 tests to prove that the certificate-authenticated role OID resolves correctly, that a different role cannot be selected, and that revoked/expired sessions are rejected.
