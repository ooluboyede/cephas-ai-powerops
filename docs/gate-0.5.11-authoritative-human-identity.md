# Gate 0.5.11 — Authoritative Human Identity Architecture

**Status:** Architecture decision proposed; implementation and security acceptance pending.  
**Repository:** `ooluboyede/cephas-ai-powerops`  
**PR:** #21 — remain open, draft and unmerged.  
**Finding addressed:** Megabusters F-01 (HIGH), database maker-checker identity can be forged.

## 1. Decision

Do not treat `verifier_subject`, an application-supplied actor claim, or a caller-set PostgreSQL GUC as authoritative database identity.

The current design uses one BU-scoped PostgreSQL login for multiple authenticated human users. PostgreSQL can identify that shared login, but cannot independently distinguish the human request subjects multiplexed through it. A trigger that compares `NEW.verifier_subject` with `recovery_outcomes.recorded_by` therefore proves only that two supplied strings differ; it does not prove two different humans acted.

**Proposed target:** customer-controlled, short-lived PostgreSQL client-certificate identity per authenticated human session, issued by a customer-operated identity broker after it validates the user's OIDC access token.

The database identity must be derived from the authenticated PostgreSQL connection (the login identity / `session_user`) and a protected customer-managed mapping to the immutable OIDC issuer + subject. It must not be read from an INSERT field or a freely mutable session setting.

## 2. Trust flow

1. The user authenticates with the customer's configured OIDC provider. PowerOps validates signature, pinned algorithm, issuer, audience, expiry and required claims.
2. A customer-operated identity broker independently validates the access token (or validates a cryptographically authenticated token-exchange assertion from the API tier). It checks the issuer + subject, tenant, BU and required finance-verifier entitlement against customer-controlled identity policy.
3. The broker issues a short-lived client certificate for that one subject and BU-bound database role. The private key is generated and retained in the approved customer-controlled execution boundary; the API must not receive a reusable fleet-wide signing key or the broker CA private key.
4. PostgreSQL verifies the client certificate using customer-configured TLS client-certificate authentication and a strict certificate-to-role mapping. Each human principal is a distinct LOGIN role; it is never a member of another human's role.
5. A protected database mapping binds the authenticated login role OID to issuer, subject, tenant, BU, active state and certificate/credential lifecycle metadata. The mapping is provisioned only by a controlled migration/provisioning authority.
6. The database resolves the actor from the authenticated connection identity. The recovery verification trigger obtains that actor from the protected mapping, verifies scope and active status, and compares it to the outcome recorder's protected actor identity.
7. Verification insertion and its audit event remain in one transaction. Direct SQL through a human's database connection is subject to the same database-side identity and maker-checker checks.

## 3. PostgreSQL role and identity invariants

- No human login has SUPERUSER, CREATEDB, CREATEROLE, REPLICATION or BYPASSRLS.
- No human login can SET ROLE to another human principal or to a privileged/provisioner role.
- Human login roles receive only the required least-privilege grants for their own BU; membership grants, where used for shared object privileges, must be non-switchable by the login and verified on PostgreSQL 14–17. Prefer direct grants if they produce a smaller and more auditable privilege surface.
- Database actor resolution uses the server-authenticated login identity, not `current_user` where a SECURITY DEFINER execution context could change it. SECURITY DEFINER functions must use a fixed safe search_path and explicit ownership/grants.
- The protected actor mapping is not writable by application/runtime roles. It is keyed by role OID and bound to the customer identity issuer + immutable subject, tenant and BU.
- Revoked, expired, disabled, retired or remapped identities fail closed.
- The certificate subject and mapping must be checked at connection establishment and again at transaction use where expiry/revocation semantics require it. Define and test the maximum stale-session window.
- RLS tenant/BU enforcement remains mandatory. Authentication identity does not replace row-scope isolation.

## 4. Recovery verification schema changes required

The present `recovery_verifications.verifier_subject` field is caller-supplied by the repository. The target migration must make the database authoritative:

- Replace or constrain the caller-writable verifier identity with a database-derived actor identity.
- Add a protected actor identity mapping and a database function that resolves the authenticated actor from the connection login.
- Record the verifier's issuer and immutable subject (or a stable internal actor UUID bound to that pair) from that function.
- Ensure the outcome's `recorded_by` is also written from the same database-authoritative identity mechanism; otherwise the maker side remains spoofable.
- Update the trigger to resolve both actors from trusted database state and reject same-actor verification.
- Reject direct INSERT attempts that attempt to provide or override actor identity.
- Keep verification and audit append-only, forced RLS, scoped composite foreign keys, and atomicity.
- Do not backfill historical actors unless the customer can provide independently verifiable evidence. Existing legacy `verified` rows remain subject to migration 0009's explicit reconciliation preflight.

## 5. Critical security caveats

This is an architecture direction, not yet a proven implementation.

- A broker that blindly trusts an API-provided subject string simply relocates the spoofing flaw. It must validate a signed customer identity assertion and enforce issuer, audience, tenant, BU and finance role policy.
- A shared broker credential or a general-purpose certificate minting endpoint available to the API tier can reintroduce impersonation. The broker must bind each issuance to a validated end-user token and enforce anti-replay, short lifetime, audience and scope.
- If the API process can read every user's private key or request arbitrary certificates without an independently validated end-user assertion, the database certificate does not establish the human actor.
- PostgreSQL certificate authentication proves possession of the private key corresponding to a trusted certificate; it does not, by itself, prove the natural person's presence. Customer MFA/step-up and token/session policy remain required.
- Certificate revocation behavior, connection pooling, session invalidation, broker outage and identity lifecycle are mandatory design/test areas.
- This design changes the current one-login-per-BU pool model. Do not bolt per-human identity onto the existing pool by setting `verifier_subject` or a GUC.

## 6. Required implementation sequence

1. **Identity contract:** define broker API, token validation rules, key custody, cert lifetime, issuer/subject mapping, role provisioning and revocation.
2. **Database migration:** create protected actor mapping and resolver; update recorder and verifier writes to use database-derived identity; remove caller control of actor fields.
3. **Connection architecture:** implement short-lived per-human authenticated DB sessions or a customer-controlled identity-aware proxy that preserves authenticated principal identity end-to-end. Do not use a shared pool that erases actor identity.
4. **Adversarial PostgreSQL tests:** test direct SQL using the actual BU/human database principals, attempted subject spoofing, forged GUCs, role switching, cross-BU access, expired/revoked certificate, broker failure and stale pooled sessions.
5. **Concurrency and audit tests:** retain Gate 0.5.10 conflict-safe insert and prove one verification + one audit event under concurrent attempts.
6. **Upgrade and rollback plan:** test clean install, existing BU runtime identities, partial provisioning, interrupted migration, legacy verified outcomes, broker outage and rollback without weakening the maker-checker invariant.
7. **Independent review:** Megabusters reviews the exact new commit and test evidence. No approval is inferred from CI.

## 7. Acceptance criteria

F-01 remains open until all are demonstrated on real PostgreSQL 14, 15, 16 and 17:

- The authenticated DB principal resolves to exactly one active issuer + subject + tenant + BU identity.
- A human cannot submit another subject in SQL or alter a GUC to impersonate another human.
- The original recorder is rejected by PostgreSQL when attempting to verify their own outcome.
- A distinct, authorised finance verifier succeeds.
- A login cannot SET ROLE or inherit another human's privileges.
- Expired, revoked, disabled and incorrectly scoped identities fail closed.
- Direct SQL and API paths enforce the same rule.
- Verification and audit records are atomic and append-only.
- CI logs show the exact reviewed commit and all matrix jobs.

## 8. Current gate disposition

- **F-01:** OPEN — architecture proposed; no implementation or acceptance evidence yet.
- **F-02:** Source correction and concurrency test authored in commits `29aea156a0793939f5677ca28f60961500e403d2`, `d6e5981502fcfad6d34e98ec31262c2660e2f368`, and `e797199e0df07977334952401fa762e62d4b5366`; real PostgreSQL/CI execution remains unverified.
- **CI:** Not yet confirmed for the latest branch head.
- **Independent approval:** Not granted.
- **PR #21:** Keep open, draft and unmerged.
- **Production / financial PoV:** Not approved by this gate.
