# PS-02.1A.3 — Dedicated per-session PostgreSQL login identity

Status: **implemented at source level; PostgreSQL validation pending**.

Repository: `ooluboyede/cephas-ai-powerops`  
Branch: `security/revenue-assurance-gate-0.1`  
PR: #21

## Implementation

Migration `0014_per_session_human_login_identity.sql` adds a protected `human_session_actor_binding` table. Each row binds one session UUID and one unique session-role OID/name to an existing actor-role OID and immutable actor/scope snapshot. Existing actor uniqueness and finance-entitlement rows are preserved.

`provision_human_session_login(...)`:
- accepts the verified actor key and a newly generated session role name;
- re-resolves and locks the authoritative actor row, deriving finance entitlements from that row rather than request claims;
- delegates role creation to the existing NOLOGIN-first `provision_scope_login` lifecycle;
- creates the session-to-actor mapping before the transaction can commit;
- grants the same database-derived human resolver and Revenue Assurance permissions to the new session login.

The revised `resolve_authenticated_human_actor_v2()` maps session login → session binding → current actor row. Legacy directly provisioned human logins retain their previous resolution path. A session row that exists but is inactive/expired cannot fall back to the legacy actor path. The lower-level `resolve_authenticated_scope()` used by RLS also checks session expiry/revocation and the current actor's active entitlement, preventing expired sessions or actor-wide revocation from retaining ordinary scoped table access. The existing actor-revocation function now retires and tombstones every active session login for that actor, setting each to NOLOGIN.

The human audit trigger now recognizes dedicated session roles and derives their actor from the same resolver.

`retire_human_session_login(session_id, reason)` fences the exact session by deactivating its binding and scope, adding a permanent role name/OID tombstone, and setting only that session role to NOLOGIN. It is idempotent after the first successful retirement.

## Integration coverage added

`tests/postgresql/run_gate0_5_14_8_6_ps021a3.sh` and the PostgreSQL 14–17 workflow step cover:
- two concurrent session logins for one actor;
- distinct PostgreSQL role OIDs;
- identical DB-derived actor and finance entitlements;
- no role membership edges;
- denial of direct runtime access to protected session bindings;
- exact-session retirement while the other session remains usable;
- actor-wide revocation cascading to all remaining session logins;
- rejection of reused session UUIDs and role names.

## Explicit limitations

- The migration and test harness are committed but have **not yet been executed**. No PostgreSQL 14–17 pass is claimed.
- The broker still issues certificates against the actor's pre-existing role. Broker integration must call this provisioning function first, bind the returned unique role into the certificate CN, and compensate by retiring the exact role if signing or credential persistence fails.
- The connector still does not register the session UUID/backend association before application SQL. Exact backend admission registration and termination remain separate PS-02 work.
- This migration does not terminate already-connected backends on retirement; it prevents future login and causes the RLS scope resolver and human actor resolver to fail closed. Do not claim instantaneous physical connection termination.
- Customer DBA approval and least-privilege review of role creation/control-plane grants remain required.
- Migration 0013 remains an unaccepted attempt and is not applied by CI or customer deployments.

PS-02.1A.3 is **not accepted** pending real PostgreSQL 14–17 execution, review of retained logs, broker/connector integration, race tests, and independent security reassessment. PR #21 remains draft and unmerged.


## PS-02.1A.4 — Broker integration source implementation

Commits after the migration 0014 implementation:

- `7762064c765276725fdfbda220291387921c5b49`: introduce the required
  `HumanSessionRoleProvisioner` broker contract and server-generated session
  UUID / random per-session PostgreSQL role name.
- `c06be98de1ae47fddc73705d4bc209c20b756ae0`: adapt broker unit fixtures to
  use distinct per-session identities.
- `288ebfc4535bdc1c66e36335e015a2233a5eec18`: retire a provisioned session
  when API-side credential validation or persistence fails.
- `a40e6e50f016634fa8454c66f12ae2a0d6e6f2d6`: expose exact-session retirement
  through the broker contract.
- `6e44f6e4f33826c4ac98c8ecc54bd1ff0b441cbe`: test credential-store and
  identity-mismatch compensation.
- `4a0a4d5edc486de3ced5dcea90f7c9552bffbfda`: tighten fake broker retirement
  state in issuer tests.
- `79544289962edcf9c024111310077a59526a0278`: add signer-failure retirement
  test.

Source behavior now:
1. The broker validates the signed principal and existing directory actor
   binding, then consumes the replay identifier.
2. It generates a UUID and random `pwr_` role name server-side.
3. The injected customer DB provisioner must call migration 0014's
   `provision_human_session_login`, commit, and return a positive role OID.
   Actor identity and scope are revalidated by PostgreSQL; the caller does not
   provide role OIDs or finance entitlements to that SQL function.
4. The certificate CN and verification target are the new per-session role,
   not the actor's shared database login.
5. Signing, certificate validation, API identity mismatch, and credential
   persistence failures attempt exact-session retirement. An unconfirmed
   retirement raises a generic dependency failure.
6. The role OID is validated as a positive integer; the certificate and lease
   are bound to the same generated session role and UUID.

Outstanding integration requirements:
- No concrete customer PostgreSQL provisioner adapter is implemented or wired
  into a deployed broker composition root yet. The protocol is mandatory, so
  an unconfigured broker cannot be constructed successfully.
- The adapter must execute migration 0014's function with the exact argument
  contract, commit before returning, use a least-privilege control-plane
  connection, and implement idempotent exact-session retirement.
- The adapter's uncertain-commit behavior, PostgreSQL role-OID mapping,
  provision/retire races, and database audit behavior need integration tests.
- The PostgreSQL connector still needs PS-02.1A.5 session/backend registration.
  This gate does not terminate existing PostgreSQL backends.
- Tests and CI have not been run for these commits. No PostgreSQL 14–17,
  Ruff, Mypy, or full pytest result is established. This is source-level
  implementation only, not gate acceptance or production certification.
