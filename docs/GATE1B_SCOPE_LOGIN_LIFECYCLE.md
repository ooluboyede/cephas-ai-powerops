# Gate 1B — controlled PostgreSQL scope-login lifecycle

**Status:** draft implementation; not executed against PostgreSQL; not a passed security gate.

## Scope
Adds controlled provisioning and retirement functions for runtime login identities. It does not attach RLS policies to business tables and does not establish production tenant isolation.

## Provisioning sequence
1. Validate the generated role name (reserved `pwr_...` namespace) and the tenant/BU tuple.
2. Lock the singleton cluster identity row to serialize lifecycle changes.
3. Reject existing role names, prior role-name tombstones and existing bindings.
4. Create the PostgreSQL role as `NOLOGIN`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOINHERIT`, `NOREPLICATION`, `NOBYPASSRLS`.
5. Bind the actual PostgreSQL role OID and immutable scope tuple as inactive.
6. Grant only schema USAGE and resolver EXECUTE.
7. Verify role attributes and absence of role memberships.
8. Activate the binding and make LOGIN the final transition. All database changes occur in one transaction; any error rolls back the transaction.

The function accepts no password or password verifier. Credential creation/rotation must be performed by the customer's approved secret-management process outside SQL source, command history and logs. Do not connect the role until that process has installed its credential.

## Retirement / fencing sequence
1. Lock cluster identity and the target binding.
2. Insert the permanent role-OID/name tombstone.
3. Set the binding inactive.
4. Set the PostgreSQL role to NOLOGIN.
5. Commit this fencing transaction.
6. As a separate privileged operational step, terminate all remaining sessions for that role, evict connection pools, verify session count is zero, remove object ownership and grants/dependencies, and only then DROP ROLE.

The function intentionally does not drop roles or terminate sessions. This makes the durable fence the first committed action and leaves cleanup retryable. Existing sessions must be terminated before declaring retirement operationally complete. A runtime transaction that already began before the fence must be treated as potentially in-flight until session termination and transaction drain are evidenced.

## Authorization boundary
The functions are SECURITY DEFINER, owned by the non-login `powerops_provisioner` role, and revoked from PUBLIC. The migration administrator must grant EXECUTE only to a dedicated, authenticated deployment authority after review. Never grant either lifecycle function to runtime logins. Never grant runtime roles membership in another role. Never accept tenant/BU scope from an untrusted client, request body or mutable session GUC; the trusted deployment workflow must authorize the scope tuple before calling the function.

## Known limitations and risks
- Gate 1A has not been executed against a supported PostgreSQL build in this environment. Gate 1B is likewise unexecuted.
- PostgreSQL role creation and lifecycle DDL behaviour, SECURITY DEFINER privileges, catalog visibility and function ownership must be verified on the exact supported PostgreSQL major/minor build.
- PostgreSQL OIDs can be reused after role deletion. The permanent tombstone is the control; any OID collision is rejected. Role names must never be reused.
- Cluster UUID clone/restore fencing, duplicate-active-cluster prevention and backup/restore tombstone integrity remain open.
- Password provisioning, rotation, expiry, revocation and secret-manager integration remain an external customer-controlled runbook.
- Role ownership, object grants, default privileges, database CONNECT/TEMP, schema/table/sequence/function privileges, replication privileges and role-membership drift need a separate effective-privilege audit.
- The migration grants no runtime table privileges and adds no RLS policies.
- No automatic connection-pool eviction or session termination is implemented.
- The SECURITY DEFINER functions and their caller authorization model require independent security review.

## Required validation evidence before gate acceptance
- Apply migrations 0001–0003 to a disposable supported PostgreSQL instance and capture version, migration logs and exit codes.
- Provision a tenant login and a BU login; verify actual role OIDs, scope tuples, role flags, grants and resolver output.
- Prove a runtime login cannot execute lifecycle functions, assume another role, create roles, grant memberships, or mutate security metadata.
- Verify malformed role names, invalid scope tuples, duplicate names, tombstoned names and injected identifier strings are rejected.
- Inject failures after each provisioning stage and prove full rollback: no orphan role, binding, grant or active login.
- Race concurrent provisioning attempts for the same name and verify exactly one can succeed.
- Retire a login; prove new connections fail, resolver denies any existing session after the fence, sessions are terminated by the runbook, and the tombstone survives role drop and backup/restore.
- Test retries at every retirement stage and prove no identity can be reactivated or reused.
- Audit SECURITY DEFINER owner attributes, function ACLs, search_path, temp-object attacks, role memberships, object privileges and connection settings.
- Obtain independent PostgreSQL security review and exact-head CI evidence.

## Gate decision
**NOT PASSED / NOT PRODUCTION-READY** until the above evidence is attached to this commit. This implementation is a controlled lifecycle draft only.
