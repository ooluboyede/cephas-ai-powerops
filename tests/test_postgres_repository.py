from __future__ import annotations

import os
from decimal import Decimal
from uuid import UUID

import psycopg
import pytest
from fastapi import HTTPException

from powerops.postgres_repository import PostgresRevenueAssuranceRepository
from powerops.revenue_assurance import (
    CaseCreate,
    DecisionCreate,
    RecoveryOutcomeCreate,
    ScopeContext,
)

DATABASE_URL = os.environ.get("POWEROPS_TEST_DATABASE_URL")
ADMIN_DATABASE_URL = os.environ.get("POWEROPS_TEST_ADMIN_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="POWEROPS_TEST_DATABASE_URL is only configured in PostgreSQL integration CI",
)

TENANT_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BU_A1 = UUID("a1000000-0000-4000-8000-000000000001")
FINDING_A1 = UUID("d1000000-0000-4000-8000-000000000001")


def test_postgres_repository_finding_case_decision_and_recovery_roundtrip() -> None:
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

    finance = ScopeContext(TENANT_A, BU_A1, "finance-verifier-01")
    outcome = repository.record_recovery_outcome(
        finance,
        case.case_id,
        RecoveryOutcomeCreate(
            amount=Decimal("1000.2500"),
            currency="NGN",
            outcome="verified",
            evidence_reference="synthetic-bank-receipt-001",
        ),
    )
    assert outcome is not None
    assert outcome.outcome == "verified"
    assert outcome.amount == Decimal("1000.2500")

    # Use the migration administrator here so the append-only triggers are
    # exercised directly rather than merely observing runtime GRANT denial.
    assert ADMIN_DATABASE_URL is not None
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
