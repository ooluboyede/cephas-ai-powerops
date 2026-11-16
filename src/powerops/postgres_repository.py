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
    RecoveryVerificationCreate,
    RecoveryVerificationRead,
    ScopeContext,
)
from powerops.scoped_pool import ScopedConnectionPool


class PostgresRevenueAssuranceRepository:
    """Synchronous, per-operation PostgreSQL access for one BU identity."""

    def __init__(
        self,
        dsn: str,
        *,
        pool_min_size: int = 1,
        pool_max_size: int = 8,
        pool_timeout: float = 5.0,
    ) -> None:
        self._pool = ScopedConnectionPool(
            dsn,
            min_size=pool_min_size,
            max_size=pool_max_size,
            timeout=pool_timeout,
        )

    def close(self) -> None:
        """Close and drain the service-instance pool during shutdown."""
        self._pool.close()

    def pool_health(self) -> dict[str, object]:
        """Return non-secret pool health counters for operational monitoring."""
        return self._pool.health_snapshot()

    def rotate_credentials(self, new_dsn: str, scope: ScopeContext) -> None:
        """Rotate one BU login only after the replacement identity is verified."""
        self._pool.rotate_credentials(
            new_dsn,
            expected_tenant_id=scope.tenant_id,
            expected_business_unit_id=scope.business_unit_id,
        )

    @contextmanager
    def _connection(self, scope: ScopeContext) -> Iterator[Any]:
        with self._pool.connection(scope.tenant_id, scope.business_unit_id) as connection:
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
            if case is None:
                return None
            allowed_statuses = {
                "approve": {"open", "in_review"},
                "reject": {"open", "in_review", "awaiting_evidence"},
                "request_more_evidence": {"open", "in_review"},
            }
            if case["case_status"] not in allowed_statuses[payload.decision]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Decision is not valid for the current case state",
                )
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
        case_id: UUID,
        payload: RecoveryOutcomeCreate,
    ) -> RecoveryOutcomeRead | None:
        outcome_id = uuid4()
        with self._connection(scope) as connection:
            case = connection.execute(
                """
                SELECT case_status
                FROM revenue_assurance.investigation_cases
                WHERE tenant_id = %s AND business_unit_id = %s AND case_id = %s
                FOR UPDATE
                """,
                (scope.tenant_id, scope.business_unit_id, case_id),
            ).fetchone()
            if case is None:
                return None
            if case["case_status"] != "approved":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Recovery outcomes require an approved investigation case",
                )
            row = connection.execute(
                """
                INSERT INTO revenue_assurance.recovery_outcomes
                    (tenant_id, business_unit_id, outcome_id, case_id, amount,
                     currency, outcome, evidence_reference, recorded_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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

    def verify_recovery_outcome(
        self,
        scope: ScopeContext,
        outcome_id: UUID,
        payload: RecoveryVerificationCreate,
    ) -> RecoveryVerificationRead | None:
        verification_id = uuid4()
        with self._connection(scope) as connection:
            outcome = connection.execute(
                """
                SELECT recorded_by
                FROM revenue_assurance.recovery_outcomes
                WHERE tenant_id = %s AND business_unit_id = %s AND outcome_id = %s
                FOR UPDATE
                """,
                (scope.tenant_id, scope.business_unit_id, outcome_id),
            ).fetchone()
            if outcome is None:
                return None
            if outcome["recorded_by"] == scope.subject:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Maker-checker control: recovery recorder cannot verify the same outcome",
                )
            row = connection.execute(
                """
                INSERT INTO revenue_assurance.recovery_verifications
                    (tenant_id, business_unit_id, verification_id, outcome_id,
                     verifier_subject, evidence_reference, reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING verification_id, outcome_id, verifier_subject,
                          evidence_reference, reason, verified_at
                """,
                (
                    scope.tenant_id,
                    scope.business_unit_id,
                    verification_id,
                    outcome_id,
                    scope.subject,
                    payload.evidence_reference,
                    payload.reason,
                ),
            ).fetchone()
            self._append_audit(
                connection,
                scope,
                action="recovery.outcome_verified",
                entity_type="recovery_outcome",
                entity_id=str(outcome_id),
                event_data={"verification_id": str(verification_id)},
            )
        return RecoveryVerificationRead(
            verification_id=row["verification_id"],
            outcome_id=row["outcome_id"],
            verifier_subject=row["verifier_subject"],
            evidence_reference=row["evidence_reference"],
            reason=row["reason"],
            verified_at=row["verified_at"],
        )
