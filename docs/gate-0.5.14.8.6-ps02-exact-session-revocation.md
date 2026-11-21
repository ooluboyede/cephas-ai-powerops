# PS-02 — Exact-session PostgreSQL revocation

Status: orchestration contract and mock-level tests implemented; customer PostgreSQL control-plane adapter and live database evidence remain outstanding.

## Coordinator sequence

`HumanSessionRevocationCoordinator.revoke` requires an authenticated actor with the `powerops_session_revoker` role and one exact session UUID. It then:

1. Attempts exact credential-store revocation so subsequent exact-UUID reads are blocked.
2. Attempts the customer PostgreSQL admission fence even if credential-store revocation failed.
3. If fenced, asks the customer control plane to terminate backends mapped to that exact session.
4. Queries the control plane again and accepts success only when the remaining exact-session backend count is zero and credential revocation plus fencing both succeeded.
5. Writes a secret-free audit record containing the actor subject, session UUID, outcome, terminated count and per-stage boolean results.

Partial failures return a safe incomplete error and are retryable. Provider exception strings, connection credentials, certificate material and caller-supplied backend PIDs are never included in the coordinator's audit payload.

## Required customer adapter guarantees

The `SessionBackendRevocationControl` implementation is intentionally an injected customer boundary, not a generic privilege-escalation mechanism. Before acceptance it must prove:

- A trusted, separately privileged PostgreSQL control connection.
- An atomic per-session admission fence that also handles connect/revoke races.
- A trusted database-side mapping from exact session UUID to backend PID(s), not a PID supplied by the API caller.
- Termination only of the exact mapped backend(s), never all sessions for a role, tenant or business unit.
- Verification that each target backend has disappeared.
- Idempotent retries, bounded lock and statement timeouts, safe behavior for already-terminated sessions, and fail-closed behavior on database outage or insufficient privilege.
- An audit trail for both successful and partial revocation.
- A measured revocation SLA under concurrent connect/revoke load.

The existing certificate connector does not yet provide this database-side admission-fence integration, and no concrete provider/database adapter is included in this change. The protocol and mock tests do not prove PostgreSQL backend termination, transaction races, customer privilege configuration, or a revocation SLA.

## Required validation before PS-02 acceptance

1. Implement the adapter for the customer's selected PostgreSQL deployment and privilege model.
2. Add PostgreSQL integration tests for active exact-session termination, unrelated-session preservation, concurrent connection/revocation races, timeout, outage, insufficient privilege, partial completion and retry convergence.
3. Run focused tests, full pytest, Ruff, Mypy and the supported PostgreSQL version matrix.
4. Obtain independent review against the exact resulting commit.

No production acceptance, certification, deployment or merge is implied by the orchestration contract alone.
