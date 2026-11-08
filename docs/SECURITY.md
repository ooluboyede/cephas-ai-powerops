# Security and tenant isolation baseline

## Mandatory design requirements

- Tenant and business-unit isolation must be enforced by the database, not merely by API filters.
- PostgreSQL Row-Level Security (RLS) is the target enforcement mechanism for tenant-scoped operational tables.
- Tenant and business-unit context must be derived and verified server-side from authenticated identity claims. Never trust tenant IDs supplied in request bodies, query strings, or headers as authority.
- Missing, malformed, or unverifiable security context must fail closed.
- Every tenant-scoped query and write must execute within a transaction whose verified context is bound to the database session using transaction-local settings.
- Application roles must not own protected tables, bypass RLS, or possess BYPASSRLS.
- Cross-tenant and cross-business-unit adversarial tests are release blockers.
- Sensitive reads, exports, configuration changes, and approvals must be auditable.
- Secrets and signing keys must not be committed to source control.

## Future controls

FIDO2/WebAuthn MFA, RBAC/ABAC, append-only audit retention, signed model artifacts, two-person approval for sensitive actions, SIEM integration, mTLS, webhook signature verification, and licence validation are planned controls. They are not implemented by this foundation commit.

## Release rule

No release may be described as production-certified until database isolation, authentication, authorisation, audit, dependency hardening, backup/restore, observability, penetration testing, and customer acceptance have passed documented gates.
