# PowerOps Revenue Assurance API — Gate 0.1 contract

**Status:** Route layer, typed API contracts and PostgreSQL repository adapter implemented; production identity-provider integration remains gated.

Base path: /api/v1/revenue

## Trust boundary

- The API never accepts tenant_id or business_unit_id in request bodies or query parameters.
- A trusted authentication integration must validate the OIDC/JWT token and populate request.state.authenticated_principal.
- Missing authenticated principal returns HTTP 401.
- Missing repository/database adapter returns HTTP 503; the service does not silently use an in-memory store or synthetic fallback.
- Every repository method receives a server-derived tenant/business-unit scope and authenticated subject.
- The PostgreSQL adapter connects using one BU-scoped database login per configured service instance; tenant-wide database logins are not eligible for Revenue Assurance schema grants. It verifies powerops_security.resolve_authenticated_scope() for each operation and fails closed on mismatch. The initial adapter opens a fresh connection per operation; it does not multiplex different database identities through a shared pool. A managed pool and secret-rotation lifecycle remain later hardening work.
- PostgreSQL RLS in migration 0006 is the final row-level boundary; API filtering is not a substitute.

## Endpoints

| Method | Path | Purpose | Required application role |
|---|---|---|---|
| GET | /findings | List findings with status/category/limit/offset | Analyst, investigator, reviewer, approver, finance or admin |
| GET | /findings/{finding_id} | Retrieve one finding | Same as list |
| POST | /cases | Create an investigation case | Investigator or admin |
| POST | /cases/{case_id}/decisions | Record approve/reject/request-evidence decision | Approver for approve; reviewer/approver for other decisions |
| POST | /cases/{case_id}/recovery-outcomes | Record reported/verified/reversed/disputed outcome | Finance verifier for verified; finance operator/verifier otherwise |

## Data semantics

- estimated_exposure is not approved recovery and is not cash received.
- Only an authorised finance verifier may record an outcome as verified.
- No route posts a bill adjustment, refund, journal, disconnection or meter/SCADA command.
- Decisions and recovery outcomes must be append-only in the persistence implementation and auditable.
- Currency is an ISO 4217 uppercase three-letter code; money uses decimal arithmetic.
- IDs are UUIDs; timestamps are timezone-aware.

## Error contract

- 401: no trusted authenticated principal.
- 403: principal lacks the required application role.
- 404: finding or case is not visible in the authenticated database scope.
- 422: invalid request schema or bounds.
- 503: repository/database adapter is not configured.

FastAPI exposes generated API documentation at /docs and /openapi.json. These endpoints document the API; they do not imply production authentication or persistence is configured.
