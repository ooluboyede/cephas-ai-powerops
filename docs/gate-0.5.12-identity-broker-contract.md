# Gate 0.5.12 — Identity Broker Contract and Database Actor Mapping

**Status:** Contract and migration design only; no broker, certificate issuance, schema migration or per-human connection implementation is claimed.  
**PR:** #21 — keep open, draft and unmerged.  
**Finding:** Megabusters F-01 (HIGH).  
**Design inputs inspected:** `src/powerops/auth.py`, `src/powerops/scoped_pool.py`, `src/powerops/postgres_repository.py`, migrations `0003`, `0007`, `0008`, `0009`, and Gate 0.5.11 architecture decision.

## 1. Gate decision

The existing API authenticates a human subject from OIDC, but PostgreSQL connections use one BU-scoped service login shared by multiple humans. The database therefore cannot distinguish the human who made a request. Current repository writes of `scope.subject` and the Gate 0.5.6 trigger comparison do not establish database-authenticated human identity.

Gate 0.5.12 defines a customer-operated broker contract and a protected database actor mapping. It deliberately does not implement a trigger-only workaround or introduce an incomplete migration. Implementation requires customer decisions about the OIDC provider, high-assurance authentication policy, client-certificate trust, certificate-to-role mapping, and session lifecycle.

## 2. Trust boundaries and responsibilities

| Component | Permitted responsibility | Must not be trusted to |
|---|---|---|
| Customer OIDC provider | Authenticate user; issue a broker-audience token with immutable issuer/subject, tenant, BU, entitlement and assurance claims | Accept tenant/BU/role values supplied by PowerOps |
| PowerOps API | Enforce application authorization; forward the signed broker-audience token and a CSR | Assert a subject string, mint certificates, hold CA keys, select another user's database role |
| Customer identity broker | Independently validate the token; enforce customer identity policy; authorize the pre-provisioned human DB identity; sign a short-lived certificate | Trust API-provided identity fields or accept arbitrary role names |
| PostgreSQL TLS/authentication | Validate the customer CA and certificate-to-role mapping; establish a distinct authenticated DB login | Infer the human from request fields or mutable GUCs |
| Protected DB actor mapping | Resolve authenticated DB login OID to issuer + subject + tenant + BU + entitlement and active lifecycle state | Be writable by runtime application or human roles |
| Customer deployment authority | Provision/retire database principals, broker trust, CA and identity mappings | Reuse retired role names/OIDs or bypass the approved provisioning path |

The API's existing OIDC verifier remains useful for API authorization. It is not a substitute for the broker's independent verification.

## 3. Broker token contract

### 3.1 Token issuance

The customer IdP must issue a signed access token specifically for the broker, not a generic token whose audience is only the PowerOps API. The broker validates the token directly against the customer's configured issuer metadata/JWKS or through an equivalently authenticated customer identity-introspection contract.

Required claims:

- `iss`: exact allow-listed customer issuer.
- `aud`: exact broker audience configured by the customer (for example, `powerops-db-session-broker`).
- `sub`: non-empty immutable subject, scoped by issuer.
- `tenant_id` and `business_unit_id`: canonical UUIDs authorized by customer policy.
- `roles` or an equivalent entitlement claim: includes the configured finance-verifier entitlement for verification operations.
- `iat`, `nbf` when present, and `exp`: checked with a small configured clock-skew allowance; maximum token age and lifetime are customer policy.
- `jti`: unique token identifier used for replay controls.
- `acr` and/or `amr` plus `auth_time`: satisfy customer-configured MFA/step-up policy for sensitive financial verification. Missing or insufficient assurance fails closed.

The broker pins an explicitly configured signing algorithm allow-list and rejects algorithm substitution, unknown issuer, wrong audience, missing claims, invalid signature, expired/not-yet-valid token, excessive token age, invalid UUIDs, and insufficient assurance. The broker must not infer an identity from request headers or payload fields.

A nonce is not assumed to be a generic access-token claim. If the customer IdP uses a nonce or transaction-binding mechanism, its semantics must be defined in the selected token-exchange profile and verified by the broker. The broker must not claim replay resistance merely because a token contains `jti`.

### 3.2 CSR and session request

Proposed endpoint: `POST /v1/database-sessions`.

Transport requirements:
- TLS 1.3; mutual TLS or equivalent workload identity authenticates the calling PowerOps deployment to the broker.
- Broker endpoint is private to the customer deployment.
- The request contains the signed broker-audience token and a PKCS#10 CSR. It may contain an idempotency key, but no caller-selected DB role, subject, tenant, BU or entitlement.
- Broker validates CSR key type/size and proof of private-key possession. The private key is generated by the client in the approved customer-controlled execution boundary and never sent to the broker.
- The broker derives the database role only from its own protected mapping for the validated issuer + subject + tenant + BU. It never accepts a role name supplied by the API.
- Broker issues only for a pre-provisioned, active human principal and only for the exact validated scope and entitlement.

Example request shape (illustrative; token and CSR values are placeholders):

```http
POST /v1/database-sessions
Authorization: Bearer <customer-issued broker-audience access token>
Content-Type: application/json
Idempotency-Key: <unique request key>

{
  "csr_pem": "-----BEGIN CERTIFICATE REQUEST-----..."
}
```

Successful response shape:

```json
{
  "certificate_pem": "-----BEGIN CERTIFICATE-----...",
  "ca_chain_pem": "-----BEGIN CERTIFICATE-----...",
  "database_host": "customer-configured-db-host",
  "database_name": "customer-configured-db",
  "database_role": "broker-derived-preprovisioned-role",
  "expires_at": "2026-11-18T08:15:00Z",
  "session_id": "opaque-customer-generated-id"
}
```

The response must not contain a private key, CA private key, reusable signing secret, or a credential that can request arbitrary identities. The API must not be allowed to choose the `database_role`; the returned role is broker-derived and must match the authenticated certificate identity. Exact response fields and database endpoint discovery are deployment configuration, not user-controlled routing.

### 3.3 Issuance controls

- Certificate lifetime is short and customer-configured (initial design target: no more than five minutes); a shorter lifetime may be required by customer policy.
- Certificate identity is bound to one pre-provisioned database login. The certificate subject/CN mapping must be exact and unambiguous; do not use wildcard maps or a shared service role.
- Broker signs only after independently validating token, entitlement, scope, assurance and CSR.
- `jti` replay is prevented using an atomic customer-controlled issuance ledger. A retry with the same idempotency key and same token/CSR thumbprint returns the same issuance result; a changed CSR or scope is rejected. Reuse under another idempotency key is denied according to the configured one-use token policy.
- Apply per-user, per-tenant, per-BU and per-workload rate limits. Log issuance/rejection metadata without tokens, private keys, CSR private material or sensitive claims.
- CA private keys remain in customer-controlled HSM/KMS or equivalent approved signing boundary. The API process has no CA key access.
- Broker signing keys are rotated with overlapping trust and tested rollback; compromised CA rotation is a customer incident procedure, not an API operation.
- Broker outage, JWKS outage, mapping outage, revocation uncertainty, clock uncertainty beyond policy, or audit failure fail closed. No fallback to the shared BU login for maker-checker actions.

## 4. Certificate-to-database identity mapping

The customer configures PostgreSQL TLS client-certificate authentication and a strict certificate identity map. A certificate is accepted only when:
1. Its chain terminates at the customer-configured client-auth CA.
2. Its validity period and key usage are valid.
3. Its certificate identity maps to one pre-provisioned human database LOGIN role.
4. The corresponding database actor binding is active and has the expected role OID and scope.

A certificate authenticates possession of the corresponding private key; it does not by itself prove a natural person's presence. Customer MFA/step-up, token policy and endpoint/key custody remain necessary.

### 4.1 Protected database mapping (target schema)

A future additive migration should create a protected relation conceptually equivalent to:

- `cluster_id` — FK/reference to the established cluster identity.
- `role_oid` — PostgreSQL role OID, unique within the cluster.
- `role_name` — immutable role name snapshot for audit/diagnostics.
- `issuer` + `subject` — immutable OIDC identity pair; unique while active.
- `tenant_id` + `business_unit_id` — exact BU scope.
- `finance_verifier` — explicit database-enforced entitlement bit or normalized entitlement reference.
- `active`, `valid_from`, `valid_until`, `retired_at` — lifecycle.
- `certificate_serial` / `credential_id` — lifecycle reference where needed; do not treat serial alone as a human identity.

The relation must be owned by a dedicated non-login authority role, have no runtime INSERT/UPDATE/DELETE grants, and be protected against PUBLIC access. Only a controlled customer provisioning function may create, activate, revoke or retire bindings. Role OID—not role name alone—is the database identity key, and retired role names/OIDs must never be silently reused.

The exact table, constraints, provisioning function and upgrade migration are intentionally not created in this gate: the customer must first select certificate authentication and role-mapping operations for its PostgreSQL topology. A schema created before those decisions could falsely imply that PostgreSQL is actually authenticating the intended certificate identity.

### 4.2 Actor resolver

A future database function, with fixed safe `search_path` and narrowly granted EXECUTE, must resolve the authenticated connection principal using `session_user` (not a caller-supplied value and not a SECURITY DEFINER-shifted `current_user`). It joins the protected mapping by current cluster identity and the authenticated role OID.

The resolver returns only the minimum actor context required by database triggers and repository operations:
- immutable issuer + subject (or a stable internal actor UUID bound to that pair);
- tenant and business unit;
- finance-verifier entitlement;
- active/valid lifecycle status.

It must reject absent, ambiguous, inactive, expired, retired, out-of-scope or non-human bindings. A GUC, request field, SQL parameter or application-provided `verifier_subject` must never override the resolver.

## 5. Required repository and schema changes after contract approval

The implementation gate must update both sides of maker-checker identity:

1. **Recorder:** `recovery_outcomes.recorded_by` must be populated from the database actor resolver, not `scope.subject`. Existing rows must not be silently rewritten or assigned invented identities.
2. **Verifier:** remove caller control of `verifier_subject`; use a database default/trigger or a controlled insert function to write the resolved actor.
3. **Trigger:** compare trusted actor identifiers resolved from protected mappings for both recorder and verifier; require active finance-verifier entitlement and exact tenant/BU scope.
4. **Audit:** `audit_events.actor_subject` must use the same database-derived actor for sensitive maker-checker operations. Verification and audit stay in one transaction.
5. **Privileges:** revoke direct runtime ability to write actor columns. Use column-level grants or a controlled SECURITY DEFINER function with fixed search path and explicit owner/grants. Confirm that table owner, provisioner and runtime identities cannot be confused.
6. **Direct SQL:** direct SQL under a human certificate must enforce the same identity and separation rules as the API.
7. **Existing non-human service operations:** explicitly classify them and do not silently map them to a human. Human maker-checker actions require a human principal; service automation needs a separate policy and must not satisfy a human-verifier requirement.

## 6. Connection and pool redesign

The current `ScopedConnectionPool` holds one DSN and one BU login. It cannot safely multiplex human identities while preserving the database-authenticated actor. Gate 0.5.13 must select and implement one of these patterns:

- **Per-human session pool:** a pool is bound to one human certificate/role and cannot be shared across subjects. Pool keys include the authenticated actor and credential generation; eviction is mandatory on logout, token expiry, certificate expiry, revocation, scope change and role retirement.
- **Customer-controlled identity-aware database proxy:** the proxy validates end-user proof and preserves a distinct authenticated database identity end-to-end. It must not collapse all humans to a shared DB role or allow caller-selected actor metadata.

A conventional shared BU pool plus `SET ROLE`, `SET SESSION AUTHORIZATION`, a GUC, request-local subject, or caller-supplied verifier field is not an acceptable implementation. PostgreSQL 14–17 role membership and certificate-map behavior must be verified on the selected topology. Stale pooled sessions must be terminated or fenced when credentials are revoked; certificate expiry alone does not necessarily terminate an already-authenticated PostgreSQL session.

## 7. Revocation, replay and operational lifecycle

- Customer IdP disablement and entitlement removal propagate to broker issuance denial.
- Broker maintains a customer-controlled session/certificate ledger linking issuer + subject + scope + role OID + certificate serial + expiry.
- Revocation disables new issuance immediately and fences the database role/binding; active sessions are explicitly terminated or invalidated within a documented maximum revocation window.
- The database actor resolver checks active binding state at transaction use, so a revoked binding fails closed even if a TLS session remains open.
- The deployment runbook covers lost device keys, stolen tokens, CA compromise, broker outage, IdP/JWKS rotation, clock drift, database failover and emergency human access.
- Audit logs record issuance, denial, revocation, role provisioning and session termination with correlation IDs, never bearer tokens or private material.

## 8. Required adversarial and integration tests

The implementation must provide executable tests against real PostgreSQL 14, 15, 16 and 17, with the customer-selected TLS and certificate mapping configuration:

1. Two different human principals in the same BU authenticate as distinct PostgreSQL `session_user` values.
2. A user cannot submit another `verifier_subject` through API or direct SQL.
3. Forged GUCs and request fields do not change the actor resolved by the database.
4. Original recorder cannot verify own outcome through API or direct SQL.
5. Distinct active finance verifier succeeds.
6. User without finance-verifier entitlement is rejected by PostgreSQL.
7. Cross-tenant and cross-BU certificates/roles are denied by authentication and RLS.
8. Role switching, SET ROLE, session authorization changes and privileged membership attempts fail.
9. Expired, revoked, disabled, wrong-issuer, wrong-audience, wrong-scope and insufficient-assurance tokens cannot obtain a certificate.
10. Expired/revoked/unknown-CA/wrong-role certificates fail authentication; already-open sessions are fenced within the documented revocation window.
11. Replayed `jti`, CSR substitution, idempotency-key reuse with changed input and rate-limit exhaustion are rejected.
12. Broker/JWKS/database/ledger/audit outages fail closed; no fallback to shared BU login occurs.
13. Concurrent verification retains one verification and one audit event, with one success and one HTTP 409.
14. Clean install, existing BU logins, partial provisioning, interrupted migration, retirement and rollback are exercised without weakening the invariant.

Tests must show actual authenticated PostgreSQL principals and SQL setup. Mock-only tests are supplementary and cannot close F-01.

## 9. Implementation sequencing and acceptance

- **0.5.12 (this gate):** contract and database mapping design. No runtime security control is claimed complete.
- **0.5.13:** customer topology decision, broker reference implementation/interface, issuer policy and certificate-to-role proof of concept in an isolated test environment.
- **0.5.14:** protected actor mapping migration and resolver; recorder and verifier actor derivation; adversarial direct-SQL tests.
- **0.5.15:** identity-preserving connection lifecycle, revocation/session fencing, upgrade and PostgreSQL 14–17 matrix.
- **0.5.16:** exact-SHA CI evidence and independent Megabusters review of the implementation and adversarial results.

F-01 remains OPEN until all required database and identity tests pass and independent review accepts the exact commit. F-02 remains pending exact-commit real-PostgreSQL execution of the conflict and concurrency tests.

## 10. Current disposition

- **Contract:** documented as a proposed customer-controlled integration contract.
- **Broker implementation:** not present.
- **Certificate authority / issuance:** not configured or tested.
- **Database actor mapping / resolver:** not implemented.
- **Per-human connection architecture:** not implemented.
- **F-01:** OPEN; merge and financial PoV blocker.
- **F-02:** source/test correction authored; real PostgreSQL execution still unverified for current head.
- **CI:** no result is inferred from this documentation commit.
- **Independent approval:** not granted.
- **PR #21:** keep open, draft and unmerged.
