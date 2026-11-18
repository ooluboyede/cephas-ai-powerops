from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.rows import dict_row

from powerops.auth import AuthenticatedPrincipal
from powerops.human_postgres_repository import PostgresHumanRevenueAssuranceRepository
from powerops.human_sessions import HumanDatabaseSession, HumanSessionPrincipal
from powerops.postgres_repository import PostgresRevenueAssuranceRepository
from powerops.revenue_assurance import (
    CaseCreate,
    DecisionCreate,
    RecoveryOutcomeCreate,
    RecoveryVerificationCreate,
    ScopeContext,
)

DATABASE_URL = os.environ.get("POWEROPS_TEST_DATABASE_URL")
ADMIN_DATABASE_URL = os.environ.get("POWEROPS_TEST_ADMIN_DATABASE_URL")
TEST_PASSWORD = os.environ.get(
    "POWEROPS_TEST_PASSWORD", "Gate1E-Disposable-Only-ChangeMe"
)
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="POWEROPS_TEST_DATABASE_URL is only configured in PostgreSQL integration CI",
)

TENANT_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BU_A1 = UUID("a1000000-0000-4000-8000-000000000001")
FINDING_A1 = UUID("d1000000-0000-4000-8000-000000000001")
ISSUER = "https://idp.customer.example/tenant-a"


class CiPasswordHumanConnector:
    """CI-only password adapter; production uses the customer certificate connector."""

    def connect(self, principal: HumanSessionPrincipal) -> psycopg.Connection:
        if DATABASE_URL is None:
            raise RuntimeError("PostgreSQL integration URL is not configured")
        role = (
            "pwr_gate0144_operator"
            if principal.finance_operator
            else "pwr_gate0144_verifier"
        )
        return psycopg.connect(
            DATABASE_URL,
            user=role,
            password=TEST_PASSWORD,
            row_factory=dict_row,
        )


def finance_principal(*, operator: bool) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        issuer=ISSUER,
        subject="human-operator-0144" if operator else "human-verifier-0144",
        tenant_id=TENANT_A,
        business_unit_id=BU_A1,
        roles=frozenset({"finance_operator" if operator else "finance_verifier"}),
    )


def test_postgres_repository_finding_case_decision_and_human_recovery_roundtrip() -> None:
    assert DATABASE_URL is not None
    repository = PostgresRevenueAssuranceRepository(DATABASE_URL)
    investigator = ScopeContext(TENANT_A, BU_A1, "investigator-01")

    page = repository.list_findings(
        investigator,
        finding_status=None,
        category="billing_gap",
        limit=20,
        offset=0,
    )
    assert page.total == 1
    assert page.items[0].finding_id == FINDING_A1
    assert page.items[0].estimated_exposure == Decimal("125000.0000")

    finding = repository.get_finding(investigator, FINDING_A1)
    assert finding is not None

    case = repository.create_case(
        investigator,
        CaseCreate(
            finding_id=FINDING_A1,
            summary="Investigate synthetic billing exception",
            reason="A synthetic meter read has no matching billing record.",
        ),
    )
    assert case.status == "open"

    with pytest.raises(HTTPException) as exc_info:
        repository.record_decision(
            investigator,
            case.case_id,
            DecisionCreate(
                decision="approve",
                reason="Attempt to approve a case created by the same subject.",
            ),
        )
    assert exc_info.value.status_code == 409

    approver = ScopeContext(TENANT_A, BU_A1, "approver-01")
    decision = repository.record_decision(
        approver,
        case.case_id,
        DecisionCreate(
            decision="approve",
            reason="Independent reviewer validated the synthetic evidence.",
        ),
    )
    assert decision is not None
    assert decision.decision == "approve"

    with pytest.raises(HTTPException) as state_error:
        repository.record_decision(
            approver,
            case.case_id,
            DecisionCreate(
                decision="reject",
                reason="Attempt to change an already approved investigation case.",
            ),
        )
    assert state_error.value.status_code == 409

    human_session = HumanDatabaseSession(CiPasswordHumanConnector())
    human_repository = PostgresHumanRevenueAssuranceRepository(human_session)
    maker = finance_principal(operator=True)
    verifier = finance_principal(operator=False)

    outcome = human_repository.record_recovery_outcome(
        maker,
        case.case_id,
        RecoveryOutcomeCreate(
            amount=Decimal("1000.2500"),
            currency="NGN",
            outcome="reported",
            evidence_reference="synthetic-bank-receipt-001",
        ),
    )
    assert outcome is not None
    assert outcome.outcome == "reported"
    assert outcome.amount == Decimal("1000.2500")
    assert outcome.recorded_by == f"{ISSUER}|human-operator-0144"

    # A finance maker cannot use the verifier path, even with a forged verifier field.
    with psycopg.connect(
        DATABASE_URL,
        user="pwr_gate0144_operator",
        password=TEST_PASSWORD,
        row_factory=dict_row,
    ) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                INSERT INTO revenue_assurance.recovery_verifications
                    (tenant_id, business_unit_id, verification_id, outcome_id,
                     verifier_subject, evidence_reference, reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    TENANT_A,
                    BU_A1,
                    uuid4(),
                    outcome.outcome_id,
                    f"{ISSUER}|human-operator-0144",
                    "same-actor-evidence",
                    "Maker role must not perform finance verification.",
                ),
            )

    verification = human_repository.verify_recovery_outcome(
        verifier,
        outcome.outcome_id,
        RecoveryVerificationCreate(
            evidence_reference="independent-bank-confirmation",
            reason="Independent settlement evidence reconciled.",
        ),
    )
    assert verification is not None
    assert verification.verifier_subject == f"{ISSUER}|human-verifier-0144"

    with pytest.raises(HTTPException) as duplicate_verification:
        human_repository.verify_recovery_outcome(
            verifier,
            outcome.outcome_id,
            RecoveryVerificationCreate(
                evidence_reference="duplicate-independent-confirmation",
                reason="A second verification attempt must return a conflict.",
            ),
        )
    assert duplicate_verification.value.status_code == 409

    # Race two independent DB sessions for one verifier and outcome. Exactly one
    # insert commits; the other returns conflict without a second audit append.
    concurrent_outcome = human_repository.record_recovery_outcome(
        maker,
        case.case_id,
        RecoveryOutcomeCreate(
            amount=Decimal("2000.0000"),
            currency="NGN",
            outcome="reported",
            evidence_reference="synthetic-concurrent-recovery-002",
        ),
    )
    assert concurrent_outcome is not None
    barrier = Barrier(2)

    def attempt_concurrent_verification(_: str) -> str:
        barrier.wait(timeout=10)
        try:
            result = human_repository.verify_recovery_outcome(
                verifier,
                concurrent_outcome.outcome_id,
                RecoveryVerificationCreate(
                    evidence_reference="concurrent-independent-evidence",
                    reason="Concurrent independent verification race test.",
                ),
            )
            assert result is not None
            return "created"
        except HTTPException as exc:
            assert exc.status_code == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                attempt_concurrent_verification,
                ("submit-1", "submit-2"),
            )
        )
    assert sorted(results) == ["conflict", "created"]

    assert ADMIN_DATABASE_URL is not None
    with psycopg.connect(ADMIN_DATABASE_URL) as connection:
        verification_count = connection.execute(
            """
            SELECT count(*)
            FROM revenue_assurance.recovery_verifications
            WHERE tenant_id = %s AND business_unit_id = %s AND outcome_id = %s
            """,
            (TENANT_A, BU_A1, concurrent_outcome.outcome_id),
        ).fetchone()[0]
        audit_count = connection.execute(
            """
            SELECT count(*)
            FROM revenue_assurance.audit_events
            WHERE tenant_id = %s AND business_unit_id = %s
              AND action = 'recovery.outcome_verified' AND entity_id = %s
            """,
            (TENANT_A, BU_A1, str(concurrent_outcome.outcome_id)),
        ).fetchone()[0]
        audit_actors = connection.execute(
            """
            SELECT action, actor_subject
            FROM revenue_assurance.audit_events
            WHERE tenant_id = %s AND business_unit_id = %s
              AND entity_id = %s
              AND action IN ('recovery.outcome_recorded','recovery.outcome_verified')
            ORDER BY action
            """,
            (TENANT_A, BU_A1, str(outcome.outcome_id)),
        ).fetchall()
    assert verification_count == 1
    assert audit_count == 1
    assert {row[1] for row in audit_actors} == {
        f"{ISSUER}|human-operator-0144",
        f"{ISSUER}|human-verifier-0144",
    }

    with psycopg.connect(ADMIN_DATABASE_URL) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                UPDATE revenue_assurance.case_decisions
                SET reason = 'tampered'
                WHERE decision_id = %s
                """,
                (decision.decision_id,),
            )
    with psycopg.connect(ADMIN_DATABASE_URL) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                UPDATE revenue_assurance.recovery_outcomes
                SET evidence_reference = 'tampered'
                WHERE outcome_id = %s
                """,
                (outcome.outcome_id,),
            )


def test_database_scope_mismatch_is_denied() -> None:
    assert DATABASE_URL is not None
    repository = PostgresRevenueAssuranceRepository(DATABASE_URL)
    wrong_scope = ScopeContext(
        tenant_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        business_unit_id=UUID("b1000000-0000-4000-8000-000000000001"),
        subject="tenant-b-user",
    )
    with pytest.raises(HTTPException) as exc_info:
        repository.list_findings(
            wrong_scope,
            finding_status=None,
            category=None,
            limit=10,
            offset=0,
        )
    assert exc_info.value.status_code == 403
