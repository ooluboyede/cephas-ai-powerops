# Gate 0.5.14.2.1 — customer certificate-authenticated PostgreSQL connector

## Implemented

- Added `PsycopgHumanSessionConnector`, a production-shaped adapter that opens a new physical psycopg connection for one verified human principal; it does not use a pool.
- Credentials are supplied by a trusted customer credential-provider interface. Issuer, subject, tenant and business unit must exactly match the verified API principal.
- The database role is accepted only from that trusted provider and must match the restricted `pwr_...` role pattern. The caller cannot supply a DSN, role, startup option, GUC or `SET ROLE`.
- PostgreSQL TLS is configured with `sslmode=verify-full`, customer root CA, client certificate and private key; the connector sets a bounded connection timeout and disables autocommit.
- Certificate expiry must be timezone-aware, unexpired and no more than five minutes ahead. Certificate files must exist as regular files; the private key must not be group/world accessible on POSIX filesystems.
- psycopg is loaded lazily, so non-PostgreSQL application paths do not require the optional driver at import time.
- Tests use a fake connection factory and temporary certificate-path fixtures. They validate TLS settings, identity mismatch, role injection, expiry, file permissions and dependency failure.

## Trust boundary and limitations

- The credential provider is an interface; it is not yet backed by a live broker endpoint or secure customer credential vault.
- The customer must configure PostgreSQL `hostssl` certificate authentication and a certificate map that binds the certificate CN to the exact provisioned LOGIN role. The certificate CN and chain must be validated by the customer CA adapter.
- The connector's tests do not perform a live TLS handshake or prove customer CA chain validation.
- API issuer propagation and repository routing through `HumanDatabaseSession` remain subsequent integration work. The existing shared BU repository must not be used for finance-sensitive maker/verifier writes.
- This increment alone does not close Megabusters F-01 and does not certify production readiness.
