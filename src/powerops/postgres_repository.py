"""PostgreSQL repository for the Revenue Assurance API.

Each repository instance is configured with one BU-scoped PostgreSQL login.
Connections are not multiplexed across tenant/BU identities. Every operation
resolves the authenticated database scope before issuing domain SQL; PostgreSQL
RLS remains the final data boundary.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from json import dumps
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status

from powerops.revenue_assurance import (
    CaseCreate,
    CaseRead,
    DecisionCreate,
    DecisionRead,
    FindingPage,
    FindingRead,
    RecoveryOutcomeCreate,
    RecoveryOutcomeRead,
    ScopeContext,
)


class PostgresRevenueAssuranceRepository:
    """Synchronous, per-operation PostgreSQL access for one BU identity."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("A PostgreSQL DSN is required")
        self._dsn = dsn

    @contextmanager
    def _connection(self, scope: ScopeContext) -> Iterator[Any]:
        # Import lazily so deployments without DATABASE_URL do not need to load
        # the optional PostgreSQL driver merely to serve liveness endpoints.
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            identity = connection.execute(
                """
                SELECT tenant_id, scope_kind, business_unit_id
                FROM powerops_security.resolve_authenticated_scope()
                """
            ).fetchone()
            if (
                identity is None
                or identity["scope_kind"] != "business_unit"
                or identity["tenant_id"] != scope.tenant_id
                or identity["business_unit_id"] != scope.business_unit_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Database login scope does not match authenticated business unit",
                )
            yield connection

    @staticmethod
    def _append_audit(
        connection: Any,
        scope: ScopeContext,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        event_data: dict[str, object],
    ) -> None:
        connection.execute(
            """
            INSERT INTO revenue_assurance.audit_events
                (tenant_id, business_unit_id, event_id, request_id, actor_subject,
                 action, entity_type, entity_id, event_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                scope.tenant_id,
                scope.business_unit_id,
                uuid4(),
                str(uuid4()),
                scope.subject,
                action,
                entity_type,
                entity_id,
                dumps(event_data, separators=(",", ":"), sort_keys=True),
            ),
        )

    @staticmethod
    def _finding(row: dict[str, Any]) -> FindingRead:
        return FindingRead(
            finding_id=row["finding_id"],
            category=row["category"],
            status=row["finding_status"],
            currency=str(row["currency"]).strip(),
            estimated_exposure=row["estimated_exposure"],
            evidence_summary=row["evidence_summary"],
            observed_at=row["observed_at"],
        )

    def list_findings(
        self,
        scope: ScopeContext,
        *,
        finding_status: str | None,
        category: str | None,
        limit: int,
        offset: int,
    ) -> FindingPage:
        clauses = ["tenant_id = %s", "business_unit_id = %s"]
        parameters: list[object] = [scope.tenant_id, scope.business_unit_id]
        if finding_status is not None:
            clauses.append("finding_status = %s")
            parameters.append(finding_status)
        if category is not None:
            clauses.append("category = %s")
            parameters.append(category)
        where_clause = " AND ".join(clauses)

        with self._connection(scope) as connection:
            total_row = connection.execute(
                "SELECT count(*) AS total FROM revenue_assurance.findings WHERE "
                + where_clause,
                parameters,
            ).fetchone()
            rows = connection.execute(
                """
                SELECT finding_id, category, finding_status, currency,
                       estimated_exposure, evidence_summary, observed_at
                FROM revenue_assurance.findings
                WHERE """
                + where_clause
                + " ORDER BY created_at DESC, finding_id LIMIT %s OFFSET %s",
                [*parameters, limit, offset],
            ).fetchall()
        return FindingPage(
            items=[self._finding(row) for row in rows],
            total=int(total_row["total"]),
            limit=limit,
            offset=offset,
        )

    def get_finding(self, scope: ScopeContext, finding_id: UUID) -> FindingRead | None:
        with self._connection(scope) as connection:
            row = connection.execute(
                """
                SELECT finding_id, category, finding_status, currency,
                       estimated_exposure, evidence_summary, observed_at
                FROM revenue_assurance.findings
                WHERE tenant_id = %s AND business_unit_id = %s AND finding_id = %s
                """,
                (scope.tenant_id, scope.business_unit_id, finding_id),
            ).fetchone()
        return self._finding(row) if row is not None else None

    def create_case(self, scope: ScopeContext, payload: CaseCreate) -> CaseRead:
        case_id = uuid4()
        with self._connection(scope) as connection:
            row = connection.execute(
                """
                INSERT INTO revenue_assurance.investigation_cases
                    (tenant_id, business_unit_id, case_id, finding_id, case_status,
                     summary, opening_reason, created_by)
                SELECT %s, %s, %s, finding.finding_id, 'open', %s, %s, %s
                FROM revenue_assurance.findings AS finding
                WHERE finding.tenant_id = %s
                  AND finding.business_unit_id = %s
                  AND finding.finding_id = %s
                RETURNING case_id, finding_id, case_status, created_by, created_at
                """,
                (
                    scope.tenant_id,
                    scope.business_unit_id,
                    case_id,
                    payload.summary,
                    payload.reason,
                    scope.subject,
                    scope.tenant_id,
                    scope.business_unit_id,
                    payload.finding_id,
                ),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Finding not found")
            self._append_audit(
                connection,
                scope,
                action="investigation.case_created",
                entity_type="investigation_case",
                entity_id=str(row["case_id"]),
                event_data={"finding_id": str(row["finding_id"])},
            )
        return CaseRead(
            case_id=row["case_id"],
            finding_id=row["finding_id"],
            status=row["case_status"],
            created_by=row["created_by"],
            created_at=row["created_at"],
        )

    def record_decision(
        self,
        scope: ScopeContext,
        case_id: UUID,
        payload: DecisionCreate,
    ) -> DecisionRead | None:
        decision_id = uuid4()
        target_status = {
            "approve": "approved",
            "reject": "rejected",
            "request_more_evidence": "awaiting_evidence",
        }[payload.decision]
        with self._connection(scope) as connection:
            case = connection.execute(
                """
                SELECT created_by, case_status
                FROM revenue_assurance.investigation_cases
                WHERE tenant_id = %s AND business_unit_id = %s AND case_id = %s
                FOR UPDATE
                """,
                (scope.tenant_id, scope.business_unit_id, case_id),
            ).fetchone()
            if case is None or case["case_status"] in ("closed", "rejected"):
                return None
            if payload.decision == "approve" and case["created_by"] == scope.subject:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Maker-checker control: case creator cannot approve the same case",
                )
            row = connection.execute(
                """
                INSERT INTO revenue_assurance.case_decisions
                    (tenant_id, business_unit_id, decision_id, case_id,
                     decision, actor_subject, reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING decision_id, case_id, decision, actor_subject, reason, decided_at
                """,
                (
                    scope.tenant_id,
                    scope.business_unit_id,
                    decision_id,
                    case_id,
                    payload.decision,
                    scope.subject,
                    payload.reason,
                ),
            ).fetchone()
            connection.execute(
                """
                UPDATE revenue_assurance.investigation_cases
                SET case_status = %s
                WHERE tenant_id = %s AND business_unit_id = %s AND case_id = %s
                """,
                (target_status, scope.tenant_id, scope.business_unit_id, case_id),
            )
            self._append_audit(
                connection,
                scope,
                action="investigation.decision_recorded",
                entity_type="investigation_case",
                entity_id=str(case_id),
                event_data={"decision": payload.decision},
            )
        return DecisionRead(
            decision_id=row["decision_id"],
            case_id=row["case_id"],
            decision=row["decision"],
            actor_subject=row["actor_subject"],
            reason=row["reason"],
            decided_at=row["decided_at"],
        )

    def record_recovery_outcome(
        self,
        scope: ScopeContext,
        case_id: Any,
        payload: RecoveryOutcomeCreate,
    ) -> RecoveryOutcomeRead | None:
        outcome_id = uuid4()
        with self._connection(scope) as connection:
            case = connection.execute(
                """
                SELECT case_status
                FROM revenue_assurance.investigation_cases
                WHERE tenant_id = %s AND business_unit_id = %s AND case_id = %s
                """,
                (scope.tenant_id, scope.business_unit_id, case_id),
            ).fetchone()
            if case is None or case["case_status"] != "approved":
                return None
            row = connection.execute(
                """
                INSERT INTO revenue_assurance.recovery_outcomes
                    (tenant_id, business_unit_id, outcome_id, case_id, amount,
                     currency, outcome, evidence_reference, recorded_by,
                     verified_by, verified_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s = 'verified' THEN %s ELSE NULL END,
                    CASE WHEN %s = 'verified' THEN now() ELSE NULL END)
                RETURNING outcome_id, case_id, amount, currency, outcome,
                          recorded_by, recorded_at
                """,
                (
                    scope.tenant_id,
                    scope.business_unit_id,
                    outcome_id,
                    case_id,
                    payload.amount,
                    payload.currency,
                    payload.outcome,
                    payload.evidence_reference,
                    scope.subject,
                    payload.outcome,
                    scope.subject,
                    payload.outcome,
                ),
            ).fetchone()
            self._append_audit(
                connection,
                scope,
                action="recovery.outcome_recorded",
                entity_type="recovery_outcome",
                entity_id=str(row["outcome_id"]),
                event_data={
                    "amount": str(row["amount"]),
                    "currency": row["currency"],
                    "outcome": row["outcome"],
                    "case_id": str(case_id),
                },
            )
        return RecoveryOutcomeRead(
            outcome_id=row["outcome_id"],
            case_id=row["case_id"],
            amount=row["amount"],
            currency=str(row["currency"]).strip(),
            outcome=row["outcome"],
            recorded_by=row["recorded_by"],
            recorded_at=row["recorded_at"],
        )
