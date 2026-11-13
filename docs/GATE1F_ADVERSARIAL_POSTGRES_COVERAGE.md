# Gate 1F — adversarial PostgreSQL coverage extension

**Status: implementation submitted; execution evidence pending. Gate 1F is NOT PASSED.**

Gate 1F extends the Gate 1E disposable PostgreSQL fixture. It does not change the production schema or customer deployment.

## Added executable assertions
- Positive same-BU INSERT and UPDATE using an actual BU-scoped login.
- Cross-tenant INSERT rejected by forced RLS `WITH CHECK`.
- Cross-tenant scope-changing UPDATE rejected by forced RLS `WITH CHECK`.
- Runtime direct role-membership edges absent for fixture logins.
- Runtime feeder privileges are limited to SELECT/INSERT/UPDATE; DELETE, TRUNCATE, REFERENCES and TRIGGER are absent.
- Runtime roles retain the expected positive feeder DML grants.
- Authenticated but unmapped login fails closed in the SECURITY DEFINER scope resolver.
- Tombstoned login fails closed in the resolver.

## Execution
Run in the disposable PostgreSQL service configured by the Gate 1E workflow:

```bash
bash tests/postgresql/run_gate1f.sh
```

The script first runs Gate 1E and then the additional Gate 1F checks. The disposable password is for CI only and must never be reused.

## Important limitations / NOT TESTED
This extension does not yet prove:
- effective privileges through nested role memberships (the fixture only asserts direct edges and the runtime roles are NOINHERIT);
- provisioning rollback/failure injection and cleanup of partially-created roles;
- pool reuse, session termination, role switching or credential rotation;
- table-owner, superuser and BYPASSRLS trust-boundary behaviour;
- view, SECURITY DEFINER, partition, trigger, background-worker or future-table default-privilege paths;
- foreign-key error/side-channel behaviour;
- duplicate cluster restore/clone fencing or backup/restore safety;
- independent PostgreSQL security review.

## Acceptance
Do not mark PASS until the exact branch head has successful PostgreSQL 14–17 workflow runs, logs have been inspected, failures are corrected, and an independent reviewer signs off. This gate does not authorize IBEDC data ingestion, production deployment, or control-system integration.
