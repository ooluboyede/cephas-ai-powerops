# Gate 0.5.14.5 — database-derived finance actors and human-only recovery writes

## Implemented

- Added PostgreSQL migration `0012_database_derived_finance_actors.sql`.
- `recovery_outcomes.recorded_by` is overwritten by a BEFORE INSERT trigger using `resolve_authenticated_human_actor_v2()`; only the database-authenticated finance maker entitlement may insert.
- `recovery_verifications.verifier_subject` is overwritten by a BEFORE INSERT trigger using the same database resolver; only the finance verifier entitlement may insert.
- The verifier trigger checks the recorded maker under the same tenant/business-unit scope and rejects self-verification. Its trigger name sorts before the existing distinct-actor trigger so the DB-derived subject is checked.
- Human-session audit inserts derive `audit_events.actor_subject` from the database identity. Existing unmapped service logins retain their prior audit behavior for non-finance workflows; human-mapped sessions cannot spoof the actor.
- Added `PostgresHumanRevenueAssuranceRepository`. Recovery outcome and verification writes use `HumanDatabaseSession` only and have no shared-BU-pool fallback.
- The API recovery-outcome endpoint now requires an exclusive `finance_operator` role and the verification endpoint requires an exclusive `finance_verifier` role. Both use the human-session repository dependency and fail closed with 503 if it is not configured.
- The human repository inserts NULL for maker/verifier columns; database triggers populate them. Audit rows are inserted from the DB actor resolver.
- Updated PostgreSQL repository integration tests to exercise the human-session path. The CI-only connector uses test passwords for the provisioned test roles; production must use the customer certificate connector.
- Added SQL gate `run_gate0_5_14_5.sh` and included it before repository integration in the PostgreSQL 14–17 workflow.

## Adversarial acceptance

- Forged `recorded_by`, `verifier_subject` and human `actor_subject` values are replaced by the authenticated database actor.
- A finance verifier cannot record recovery outcomes.
- A finance maker cannot verify recovery outcomes.
- A shared BU service login without a human actor mapping cannot write recovery outcomes.
- Existing maker-checker self-verification and duplicate-verification controls remain active.
- Concurrent duplicate verification produces exactly one verification row and one audit append.
- Recovery actor identity is checked against the human-session database resolver, not caller-supplied JWT subject or GUC values.

## Remaining limitations

- The secure customer credential-store implementation, credential-provider adapter, production broker/directory/replay/CA-HSM services, PostgreSQL `hostssl` certificate map and live TLS handshake are still deployment integration work.
- The test-only password connector is not a production authentication mode.
- Other non-finance workflows still use the shared BU service pool; the new triggers specifically make the recovery maker/verifier tables fail closed for those shared identities.
- Independent external review remains outstanding. F-01 is remediated in this implementation path only if the new current-head PostgreSQL 14–17 workflow passes; no production certification is claimed before that evidence.
