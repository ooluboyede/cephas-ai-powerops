# Gate 1F — adversarial PostgreSQL scope and privilege validation

**Status: implementation submitted; execution evidence pending. Gate 1F is NOT PASSED.**

## Scope

Gate 1F extends the Gate 1E disposable PostgreSQL harness. The CI workflow runs Gate 1E first, then Gate 1F, against PostgreSQL 14, 15, 16 and 17.

## Added automated assertions

- Positive same-BU insert and update using an authenticated BU-scoped login.
- Positive tenant-scoped insert into a second business unit within the same tenant.
- Cross-tenant insert and update attempts rejected for a BU-scoped identity.
- Runtime role membership closure: runtime identities must neither be members of nor grant members to other roles.
- Effective privilege checks for schema CREATE, table DELETE/TRUNCATE/REFERENCES/TRIGGER, and privileged provisioning/retirement function execution.
- Runtime role count check to ensure the expected Gate 1E fixture identities exist.
- ENABLE ROW LEVEL SECURITY and FORCE ROW LEVEL SECURITY metadata checks on every operational table.
- SET ROLE escalation denial between two different runtime scope identities.
- Unmapped login identity fails closed through the resolver.
- Inactive scope binding fails closed.
- Retired identity tombstone denies resolver access even when a stale active binding remains.
- Invalid provisioning tuple is rejected and leaves no runtime role behind.

## Important boundaries and caveats

- The script runs only against the disposable CI database created by Gate 1E. Its fixed password is test-only and must never be reused outside CI.
- Tombstone testing deliberately inserts a retirement record while leaving the test binding active. This isolates resolver tombstone enforcement; it is not a substitute for a complete session termination, pool eviction, and retirement operations test.
- This gate does not yet prove prepared-statement or connection-pool reuse behaviour, existing-session revocation, clone/restore fencing, foreign-key side-channel resistance, partition/view/SECURITY DEFINER/background-job paths, or superuser/BYPASSRLS controls beyond checking runtime flags and RLS metadata.
- Superusers and roles with BYPASSRLS remain trusted cluster-administrator boundaries. They are not treated as ordinary application identities.
- The operational schema remains a reference schema derived from the synthetic PoV contract, not an IBEDC-approved production data model.
- No live IBEDC integration, customer data ingestion, SCADA/DMS command path, dispatch action, or production deployment is introduced.

## CI evidence from Gate 1E

The first observed Gate 1E workflow run (run ID 43411459541, head `60740dbce510b5415a5d65f1815f89a78d196cd5`) concluded **failure** across PostgreSQL 14–17. GitHub reported each matrix job as completed/failure with an empty steps list and the log-download endpoint was unavailable to this review. Therefore this result does **not** establish whether a SQL migration or assertion failed; it establishes that no successful execution evidence exists. Diagnose the Actions runner/workflow startup failure before treating the matrix as a usable database test.

## Acceptance

1. Obtain complete logs and a successful run for the exact Gate 1F head on all declared PostgreSQL versions.
2. Resolve every migration, workflow, shell, and SQL failure; do not infer success from a workflow file or a created run.
3. Review expected SQLSTATE handling and adversarial assertions with an independent PostgreSQL security reviewer.
4. Extend testing for pool/session fencing, prepared statements, FK side channels, views, SECURITY DEFINER, partitions, background jobs, and provisioning rollback before production certification.
5. Keep all stacked PRs draft/unmerged until CI, independent review, and customer deployment approval are complete.
