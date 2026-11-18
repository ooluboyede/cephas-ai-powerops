"""Human-session-only repository for finance recovery operations.

These writes never use the shared BU service pool. PostgreSQL triggers derive
maker/verifier and human audit actors from the authenticated database role OID.
"""
from __future__ import annotations

from json import dumps
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status

from powerops.auth import AuthenticatedPrincipal
from powerops.human_sessions import (
    HumanDatabaseSession,
    HumanSessionPrincipal,
    HumanSessionRejected,
)
from powerops.revenue_assurance import (
    RecoveryOutcomeCreate,
    RecoveryOutcomeRead,
    RecoveryVerificationCreate,
    RecoveryVerificationRead,
)


class PostgresHumanRevenueAssuranceRepository:
    """Finance write repository requiring one verified human PostgreSQL session."""

    def __init__(self, human_session: HumanDatabaseSession) -> None:
        self._human_session = human_session

    @staticmethod
    def _database_principal(principal: AuthenticatedPrincipal) -> HumanSessionPrincipal:
        finance_operator = "finance_operator" in principal.roles
        finance_verifier = "finance_verifier" in principal.roles
        if finance_operator == finance_verifier:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Exactly one finance maker or verifier role is required",
            )
        if not principal.issuer.startswith("https://") or not principal.subject.strip():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Verified human issuer and subject are required",
            )
        return HumanSessionPrincipal(
            issuer=principal.issuer,
            subject=principal.subject,
            tenant_id=principal.tenant_id,
            business_unit_id=principal.business_unit_id,
            finance_operator=finance_operator,
            finance_verifier=finance_verifier,
        )

    @staticmethod
    def _append_human_audit(
        connection: Any,
        principal: AuthenticatedPrincipal,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        event_data: dict[str, object],
    ) -> None:
        finance_operator = "finance_operator" in principal.roles
        finance_verifier = "finance_verifier" in principal.roles
        audit = connection.execute(
            """
            INSERT INTO revenue_assurance.audit_events
                (tenant_id, business_unit_id, event_id, request_id, actor_subject,
                 action, entity_type, entity_id, event_data)
            SELECT %s, %s, %s, %s, actor.actor_subject, %s, %s, %s, %s::jsonb
            FROM powerops_security.resolve_authenticated_human_actor_v2() AS actor
            WHERE actor.finance_operator = %s
              AND actor.finance_verifier = %s
            RETURNING event_id
            """,
            (
                principal.tenant_id,
                principal.business_unit_id,
                uuid4(),
                str(uuid4()),
                action,
                entity_type,
                entity_id,
                dumps(event_data, separators=(",", ":"), sort_keys=True),
                finance_operator,
                finance_verifier,
            ),
        ).fetchone()
        if audit is None:
            raise HumanSessionRejected("Database audit actor does not match the human session")

    def record_recovery_outcome(
        self,
        principal: AuthenticatedPrincipal,
        case_id: UUID,
        payload: RecoveryOutcomeCreate,
    ) -> RecoveryOutcomeRead | None:
        if "finance_operator" not in principal.roles or "finance_verifier" in principal.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only a distinct finance maker may record recovery outcomes",
            )
        db_principal = self._database_principal(principal)
        outcome_id = uuid4()
        with self._human_session.connection(db_principal) as connection:
            case = connection.execute(
                """
                SELECT case_status
                FROM revenue_assurance.investigation_cases
                WHERE tenant_id = %s AND business_unit_id = %s AND case_id = %s
                FOR UPDATE
                """,
                (principal.tenant_id, principal.business_unit_id, case_id),
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
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)
                RETURNING outcome_id, case_id, amount, currency, outcome,
                          recorded_by, recorded_at
                """,
                (
                    principal.tenant_id,
                    principal.business_unit_id,
                    outcome_id,
                    case_id,
                    payload.amount,
                    payload.currency,
                    payload.outcome,
                    payload.evidence_reference,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("PostgreSQL did not return the inserted recovery outcome")
            self._append_human_audit(
                connection,
                principal,
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
        principal: AuthenticatedPrincipal,
        outcome_id: UUID,
        payload: RecoveryVerificationCreate,
    ) -> RecoveryVerificationRead | None:
        if "finance_verifier" not in principal.roles or "finance_operator" in principal.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only a distinct finance verifier may verify recovery outcomes",
            )
        db_principal = self._database_principal(principal)
        verification_id = uuid4()
        with self._human_session.connection(db_principal) as connection:
            outcome = connection.execute(
                """
                SELECT recorded_by
                FROM revenue_assurance.recovery_outcomes
                WHERE tenant_id = %s AND business_unit_id = %s AND outcome_id = %s
                """,
                (principal.tenant_id, principal.business_unit_id, outcome_id),
            ).fetchone()
            if outcome is None:
                return None
            if outcome["recorded_by"] == f"{principal.issuer}|{principal.subject}":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Recovery outcome maker cannot verify the same outcome",
                )
            row = connection.execute(
                """
                INSERT INTO revenue_assurance.recovery_verifications
                    (tenant_id, business_unit_id, verification_id, outcome_id,
                     verifier_subject, evidence_reference, reason)
                VALUES (%s, %s, %s, %s, NULL, %s, %s)
                ON CONFLICT (tenant_id, business_unit_id, outcome_id) DO NOTHING
                RETURNING verification_id, outcome_id, verifier_subject,
                          evidence_reference, reason, verified_at
                """,
                (
                    principal.tenant_id,
                    principal.business_unit_id,
                    verification_id,
                    outcome_id,
                    payload.evidence_reference,
                    payload.reason,
                ),
            ).fetchone()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Recovery outcome has already been verified",
                )
            self._append_human_audit(
                connection,
                principal,
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
