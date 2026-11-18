# PowerOps Gate 0.5.14.1 — protected human actor identity foundation

## Scope

Adds a database-owned human actor registry. Each human identity is represented by a distinct PostgreSQL LOGIN role whose OID maps to an IdP issuer and subject, tenant/BU scope, and finance-verifier entitlement. Existing shared BU service logins are not auto-mapped as humans.

## Database controls

- The human actor mapping table is owned by powerops_provisioner; runtime roles receive no table privileges.
- The powerops_scope_resolver role has read-only access.
- resolve_authenticated_human_actor() derives the principal from session_user through the existing authenticated scope resolver and role OID. It accepts no identity, scope, role, or entitlement arguments.
- Caller-controlled GUC values do not participate in actor resolution.
- Provisioning creates a dedicated BU-scoped login and mapping in one transaction. Credential material remains customer-managed and is set out of band.
- Revocation marks the mapping inactive and retires the login. Existing sessions still require explicit termination and pool eviction.

## Validation

tests/postgresql/run_gate0_5_14_1.sh checks separate maker/verifier principals, role-OID resolution, GUC spoofing, runtime table privilege denial, SET ROLE denial, expired-provisioning rejection, and revocation.

## Deliberate limitations

This increment does not yet attach database-derived actors to Revenue Assurance business rows or audit events. It does not yet enforce maker-checker separation using the new mapping, implement a production CA/HSM adapter, or change API repository behavior. Those are subsequent Gate 0.5.14 increments. No production certification is claimed.
