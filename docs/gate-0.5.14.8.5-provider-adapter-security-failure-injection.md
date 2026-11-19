# Gate 0.5.14.8.5 — Provider Adapter Security and Failure-Injection Harness

- Status: implementation in progress; CI validation pending
- Branch: `security/revenue-assurance-gate-0.1`
- Scope: provider-neutral security test plan and executable mock failure-path tests
- Out of scope: selecting or deploying a provider, adding a provider SDK, customer IAM changes, live CA issuance, or production certification

## Objective

Define the security evidence every customer-approved `HumanSessionCredentialStore` adapter must produce, and make the provider outage behavior executable in the current test suite. This gate does not turn the test-only mock into a real vault or secret manager.

## Threat model and invariants

The credential store holds short-lived database client certificates and private keys. Treat the provider, network, response payload, retry path and diagnostic channel as security boundaries.

1. **Confidentiality:** private keys and certificates must not appear in logs, traces, metrics, exception text, API responses or audit payloads.
2. **Exact identity:** every read, write and revoke is addressed by the exact opaque session UUID; no list/search/fallback behavior is permitted.
3. **Scope integrity:** tenant, business unit, actor, role and exclusive finance entitlement are immutable parts of the record.
4. **Atomicity:** a failed or interrupted create must not expose a partial record; retries must not overwrite conflicting content.
5. **Fail-closed availability:** timeout, network failure, provider denial, invalid workload identity, malformed response and unavailable provider must not return stale or partial credentials.
6. **Expiry and revocation:** provider TTL cannot exceed certificate expiry; read-time expiry is mandatory; revocation prevents new retrieval and triggers the deployment's active PostgreSQL backend termination policy.
7. **Least privilege:** application workload identity can perform only the exact operations required; it cannot administer provider policies, mounts, namespaces, CA roles or audit configuration.
8. **Auditability:** provider-side audit evidence records actor/workload, operation, target reference, result and time without recording secret values.

## Executable coverage added in this gate

The mock contract suite now injects a store outage independently into:
- create/write;
- exact-session read;
- exact-session revoke.

Each path must raise `HumanSessionCredentialStoreUnavailable`; error text is checked not to disclose certificate or private-key values. These tests validate application behavior against the test mock only. They do not simulate a real network timeout, distributed provider, process crash or provider-side partial write.

## Mandatory concrete-adapter failure-injection matrix

| Injection | Expected safe behavior | Evidence required |
|---|---|---|
| DNS failure / connection refused | Fail closed; bounded timeout; no credential returned | Adapter test and sanitized logs |
| Read/write/revoke timeout | Typed unavailable error; no unbounded retry | Deadline and retry tests |
| HTTP/provider 401 or 403 | No credential fallback; no privilege escalation | Workload identity and negative IAM tests |
| Expired token / wrong audience / wrong subject | Reject before provider operation | Identity assertion tests |
| 404 / missing exact version | Treat as unavailable or absent per contract; never search another version | Exact-reference tests |
| Malformed JSON, schema mismatch or truncated payload | Reject; do not deserialize partial credential | Response validation tests |
| Provider returns wrong session/scope/version | Reject and emit secret-free security event | Adversarial response tests |
| Create succeeds remotely but client times out | Safe retry is idempotent; conflicting UUID never overwritten | Ambiguous-commit/retry test |
| Process crash during create | No partial record visible after restart | Provider-native atomicity/crash test |
| Concurrent same-UUID writes | One immutable record; identical writes idempotent; differing writes conflict | Distributed concurrency test |
| Concurrent revoke and read | No retrieval after revocation is committed under defined consistency policy | Race test and consistency statement |
| Audit sink unavailable | Follow documented fail-closed policy for sensitive operations; never silently claim audited success | Audit outage test |
| Secret-bearing provider error | Translate to safe typed error; redact response/body/headers | Log-capture and exception tests |
| Provider throttling / 429 | Bounded backoff within request deadline; no retry storm | Rate-limit test |
| CA/PKI permission denied or wrong issuer | Do not issue/store session credential | Negative CA/IAM test |
| Active PostgreSQL session during revoke | Apply approved backend termination mechanism and measured SLA | Live PostgreSQL revocation test |

## Required provider security evidence

Before a concrete adapter can be accepted, attach evidence for:
- workload identity trust chain, audience, subject binding, expiry and rotation;
- positive and negative policy tests for exact read/write/revoke permissions;
- explicit denial of list, wildcard access, policy administration and CA administration;
- encryption-at-rest configuration and customer-controlled key ownership;
- provider audit events for create/read/revoke with secret-payload redaction;
- immutable version/record semantics and provider-native atomicity;
- timeout, retry, throttling, malformed-response and ambiguous-commit behavior;
- revocation of already-open PostgreSQL backends, with measured latency;
- encrypted ephemeral key materialization, restrictive permissions and cleanup;
- live non-production TLS connection using `sslmode=verify-full`.

## Acceptance sequence

1. Ruff, Mypy, focused credential-store tests and the complete Python suite pass.
2. PostgreSQL 14, 15, 16 and 17 security/integration matrix passes.
3. The chosen provider and deployment configuration are explicitly approved by the customer.
4. Concrete-adapter failure-injection tests cover the matrix entries relevant to that provider.
5. Independent security review accepts implementation and attached provider evidence.
6. PR #21 remains draft and unmerged until product acceptance and review are complete.

## Explicit non-claims

This gate adds mock outage-path tests and a provider-neutral acceptance plan. It does not implement a Vault or other provider SDK, prove provider encryption or IAM, prove distributed atomicity, test real network failures, establish a CA hierarchy, terminate live PostgreSQL sessions, complete customer integration, or certify production readiness.
