from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from powerops.auth import AuthenticatedPrincipal
from powerops.human_postgres_repository import PostgresHumanRevenueAssuranceRepository
from powerops.revenue_assurance import RecoveryOutcomeCreate, RecoveryVerificationCreate

TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BUSINESS_UNIT = UUID("a1000000-0000-4000-8000-000000000001")
ISSUER = "https://identity.customer.example"


def principal(
    *, role: str = "finance_operator", subject: str = "maker-001"
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        issuer=ISSUER,
        subject=subject,
        tenant_id=TENANT,
        business_unit_id=BUSINESS_UNIT,
        roles=frozenset({role}),
    )


class FakeConnection:
    def __init__(self, *, case: dict[str, object] | None = None,
                 outcome: dict[str, object] | None = None,
                 inserted_outcome: dict[str, object] | None = None,
                 duplicate_verification: bool = False) -> None:
        self.case = case or {"case_status": "approved"}
        self.outcome = outcome or {"recorded_by": f"{ISSUER}|maker-001"}
        self.inserted_outcome = inserted_outcome or {
            "outcome_id": uuid4(),
            "case_id": uuid4(),
            "amount": Decimal("100.0000"),
            "currency": "NGN",
            "outcome": "reported",
            "recorded_by": f"{ISSUER}|maker-001",
            "recorded_at": datetime.now(UTC),
        }
        self.inserted_verification = (
            None
            if duplicate_verification
            else {
                "verification_id": uuid4(),
                "outcome_id": uuid4(),
                "verifier_subject": f"{ISSUER}|verifier-001",
                "evidence_reference": "bank-confirmation",
                "reason": "Independent bank confirmation reconciled.",
                "verified_at": datetime.now(UTC),
            }
        )
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> FakeConnection:
        self.calls.append((query, params))
        return self

    def fetchone(self) -> dict[str, object] | None:
        query = self.calls[-1][0]
        if "SELECT case_status" in query:
            return self.case
        if "INSERT INTO revenue_assurance.recovery_outcomes" in query:
            return self.inserted_outcome
        if "SELECT recorded_by" in query:
            return self.outcome
        if "INSERT INTO revenue_assurance.recovery_verifications" in query:
            return self.inserted_verification
        if "INSERT INTO revenue_assurance.audit_events" in query:
            return {"event_id": uuid4()}
        raise AssertionError(f"Unexpected query: {query}")


class FakeHumanSession:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection_value = connection
        self.principals: list[object] = []

    @contextmanager
    def connection(self, principal_value: object) -> Iterator[FakeConnection]:
        self.principals.append(principal_value)
        yield self.connection_value


def outcome_payload() -> RecoveryOutcomeCreate:
    return RecoveryOutcomeCreate(
        amount=Decimal("100.0000"),
        currency="NGN",
        outcome="reported",
        evidence_reference="bank-receipt-001",
    )


def verification_payload() -> RecoveryVerificationCreate:
    return RecoveryVerificationCreate(
        evidence_reference="bank-confirmation",
        reason="Independent bank confirmation reconciled.",
    )


def test_record_outcome_uses_human_session_and_database_derived_audit_actor() -> None:
    connection = FakeConnection()
    session = FakeHumanSession(connection)  # type: ignore[arg-type]
    repository = PostgresHumanRevenueAssuranceRepository(session)  # type: ignore[arg-type]
    maker = principal()

    result = repository.record_recovery_outcome(maker, uuid4(), outcome_payload())

    assert result is not None
    assert result.recorded_by == f"{ISSUER}|maker-001"
    assert len(session.principals) == 1
    insert_query, insert_params = next(
        call for call in connection.calls
        if "INSERT INTO revenue_assurance.recovery_outcomes" in call[0]
    )
    assert "recorded_by)" in insert_query
    assert insert_params is not None and len(insert_params) == 8
    assert "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)" in insert_query
    audit_query, _ = next(
        call for call in connection.calls
        if "INSERT INTO revenue_assurance.audit_events" in call[0]
    )
    assert "resolve_authenticated_human_actor_v2" in audit_query
    assert "actor.actor_subject" in audit_query


def test_verify_outcome_uses_distinct_human_verifier_session() -> None:
    connection = FakeConnection(
        outcome={"recorded_by": f"{ISSUER}|maker-001"},
        inserted_verification={
            "verification_id": uuid4(),
            "outcome_id": uuid4(),
            "verifier_subject": f"{ISSUER}|verifier-001",
            "evidence_reference": "bank-confirmation",
            "reason": "Independent bank confirmation reconciled.",
            "verified_at": datetime.now(UTC),
        },
    )
    session = FakeHumanSession(connection)  # type: ignore[arg-type]
    repository = PostgresHumanRevenueAssuranceRepository(session)  # type: ignore[arg-type]
    verifier = principal(role="finance_verifier", subject="verifier-001")

    result = repository.verify_recovery_outcome(verifier, uuid4(), verification_payload())

    assert result is not None
    assert result.verifier_subject == f"{ISSUER}|verifier-001"
    insert_query, insert_params = next(
        call for call in connection.calls
        if "INSERT INTO revenue_assurance.recovery_verifications" in call[0]
    )
    assert "verifier_subject" in insert_query
    assert insert_params is not None and insert_params[4] == "bank-confirmation"
    assert "VALUES (%s, %s, %s, %s, NULL, %s, %s)" in insert_query


@pytest.mark.parametrize(
    "value",
    [
        AuthenticatedPrincipal(
            issuer=ISSUER,
            subject="dual-role",
            tenant_id=TENANT,
            business_unit_id=BUSINESS_UNIT,
            roles=frozenset({"finance_operator", "finance_verifier"}),
        ),
        AuthenticatedPrincipal(
            issuer=ISSUER,
            subject="analyst",
            tenant_id=TENANT,
            business_unit_id=BUSINESS_UNIT,
            roles=frozenset({"revenue_analyst"}),
        ),
    ],
)
def test_repository_rejects_non_exclusive_finance_roles(value: AuthenticatedPrincipal) -> None:
    session = FakeHumanSession(FakeConnection())  # type: ignore[arg-type]
    repository = PostgresHumanRevenueAssuranceRepository(session)  # type: ignore[arg-type]

    with pytest.raises(HTTPException) as exc_info:
        repository.record_recovery_outcome(value, uuid4(), outcome_payload())
    assert exc_info.value.status_code == 403
    assert session.principals == []


def test_verifier_cannot_verify_own_database_derived_outcome() -> None:
    connection = FakeConnection(
        outcome={"recorded_by": f"{ISSUER}|verifier-001"}
    )
    session = FakeHumanSession(connection)  # type: ignore[arg-type]
    repository = PostgresHumanRevenueAssuranceRepository(session)  # type: ignore[arg-type]
    verifier = principal(role="finance_verifier", subject="verifier-001")

    with pytest.raises(HTTPException) as exc_info:
        repository.verify_recovery_outcome(verifier, uuid4(), verification_payload())
    assert exc_info.value.status_code == 409
    assert not any(
        "INSERT INTO revenue_assurance.recovery_verifications" in query
        for query, _ in connection.calls
    )


def test_duplicate_verification_returns_conflict_before_audit_append() -> None:
    connection = FakeConnection(duplicate_verification=True)
    session = FakeHumanSession(connection)  # type: ignore[arg-type]
    repository = PostgresHumanRevenueAssuranceRepository(session)  # type: ignore[arg-type]
    verifier = principal(role="finance_verifier", subject="verifier-001")

    with pytest.raises(HTTPException) as exc_info:
        repository.verify_recovery_outcome(verifier, uuid4(), verification_payload())
    assert exc_info.value.status_code == 409
    assert not any(
        "INSERT INTO revenue_assurance.audit_events" in query
        for query, _ in connection.calls
    )
