# 0.1.0 independent review remediation

Baseline reviewed: `59dd7ac95f403a465e2f01e366198027af9c6832`

This branch addresses the independent review findings without changing PR #1.

## Finding status

| Finding | Status on this branch | Closure evidence still required |
|---|---|---|
| F-01 dependency reproducibility | OPEN | Generate and commit a complete transitive dependency lock with hashes; install strictly from it in CI; verify clean reproducible installation. Do not treat version ranges or direct pins as a complete lock. |
| F-02 readiness semantics | IMPLEMENTED; CI verification pending | Readiness response now states that it is bootstrap-only and that dependency checks are not configured. Tests assert the exact contract. When required dependencies are introduced, add real checks and non-2xx failure behavior. |
| F-03 coverage gate and test breadth | IMPLEMENTED; CI verification pending | Coverage threshold is configured at 90%; configuration tests and explicit health-contract tests added. CI must demonstrate the threshold is enforced. |
| F-04 GitHub Actions pinning | IMPLEMENTED; CI verification pending | Checkout and setup-python references are pinned to full commit SHAs with release comments. Verify the referenced SHAs and successful workflow execution. |
| Starlette/httpx warning | OPEN | Capture the warning from a fresh test run, identify the exact compatible dependency set, and remove the warning without weakening tests. |

## Release controls

- This is a remediation branch based on the exact reviewed 0.1.0 commit.
- PR #1 remains unchanged, open, and unmerged.
- No authentication, tenant context, PostgreSQL RLS, utility integration, SCADA/DMS control, or autonomous operational functionality is added here.
- Do not close a finding based solely on code changes; require fresh CI evidence and independent retest of the final SHA.
