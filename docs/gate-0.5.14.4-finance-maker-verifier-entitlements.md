# Gate 0.5.14.4 — database-enforced finance maker/verifier entitlements

## Implemented

- Added PostgreSQL migration `0011_human_finance_entitlements.sql`.
- Added the protected `finance_operator` entitlement to `human_actor_binding`; existing rows default to false, preserving the prior finance-verifier mapping.
- Added a database constraint preventing one human actor mapping from holding both finance-maker and finance-verifier entitlements.
- Added `provision_human_actor_login_v2` and `resolve_authenticated_human_actor_v2()`. The resolver derives the human identity and both entitlements from the authenticated PostgreSQL `session_user` role OID and protected registry.
- Preserved the v1 provisioning and resolver functions for compatibility with existing deployed mappings.
- Updated `HumanSessionPrincipal` and `HumanDatabaseSession` to verify both entitlements using the v2 database resolver.
- Updated the certificate connector to require the stored credential entitlements to match the verified API principal.
- Updated the broker and server-side session issuer to permit exactly one of `finance_operator` or `finance_verifier`, and to compare both directory entitlements with the signed broker token.
- Updated the API session endpoint to allow either distinct finance role; dual-role principals are rejected by the server-side issuer.
- Added PostgreSQL integration script `run_gate0_5_14_4.sh` and included it in the PostgreSQL 14–17 workflow.

## Acceptance tests

- Maker and verifier logins resolve to distinct database-derived entitlements.
- Caller-set GUC values cannot change either entitlement.
- A principal with both entitlements is rejected atomically before a database login is left behind.
- Runtime cannot read the protected actor registry.
- A maker cannot `SET ROLE` to the verifier login.
- The full Python and PostgreSQL integration suites continue to run after the new migration.

## Deliberate limits

- This gate establishes separate database entitlements; it does not yet enforce `recovery_outcomes.recorded_by` or `recovery_verifications.verifier_subject` from the database session.
- The API's finance-sensitive repository operations still require routing through `HumanDatabaseSession`; the existing shared BU repository is not an acceptable fallback for those writes.
- Customer broker, durable replay store, CA/HSM, secure credential-store implementation, certificate-map deployment and live TLS handshake remain customer integration work.
- Megabusters F-01 remains open until database-derived maker/verifier fields and audit actor enforcement are implemented and adversarially tested.
- No production certification or external reviewer approval is claimed.
