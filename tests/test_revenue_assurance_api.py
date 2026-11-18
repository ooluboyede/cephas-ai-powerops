from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from powerops.identity_broker import BrokerReplayError
from powerops.human_session_issuer import HumanDatabaseSessionLease
from powerops.main import app
from powerops.revenue_assurance import (
    AuthenticatedPrincipal,
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
    get_current_principal,
)

TENANT_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ISSUER = "https://identity.customer.example"
BU_A1 = UUID("a1000000-0000-4000-8000-000000000001")
FINDING_ID = UUID("d1000000-0000-4000-8000-000000000001")
CASE_ID = UUID("f1000000-0000-4000-8000-000000000001")


class FakeRepository:
    def __init__(self) -> None:
        self.last_scope: ScopeContext | None = None
        self.recorded_outcomes: dict[UUID, str] = {}

    def list_findings(
        self,
        scope: ScopeContext,
        *,
        finding_status: str | None,
        category: str | None,
        limit: int,
        offset: int,
    ) -> FindingPage:
        self.last_scope = scope
        finding = FindingRead(
            finding_id=FINDING_ID,
            category="billing_gap",
            status=finding_status or "new",
            currency="NGN",
            estimated_exposure=Decimal("125000.0000"),
            evidence_summary="Synthetic evidence fixture",
            observed_at=datetime.now(UTC),
        )
        items = [finding] if category in (None, "billing_gap") and offset == 0 else []
        return FindingPage(items=items, total=len(items), limit=limit, offset=offset)

    def get_finding(self, scope: ScopeContext, finding_id: UUID) -> FindingRead | None:
        self.last_scope = scope
        if finding_id != FINDING_ID:
            return None
        return FindingRead(
            finding_id=FINDING_ID,
            category="billing_gap",
            status="new",
            currency="NGN",
            estimated_exposure=Decimal("125000.0000"),
            evidence_summary="Synthetic evidence fixture",
            observed_at=datetime.now(UTC),
        )

    def create_case(self, scope: ScopeContext, payload: CaseCreate) -> CaseRead:
        self.last_scope = scope
        return CaseRead(
            case_id=CASE_ID,
            finding_id=payload.finding_id,
            status="open",
            created_by=scope.subject,
            created_at=datetime.now(UTC),
        )

    def record_decision(
        self, scope: ScopeContext, case_id: UUID, payload: DecisionCreate
    ) -> DecisionRead | None:
        self.last_scope = scope
        if case_id != CASE_ID:
            return None
        return DecisionRead(
            decision_id=uuid4(),
            case_id=case_id,
            decision=payload.decision,
            actor_subject=scope.subject,
            reason=payload.reason,
            decided_at=datetime.now(UTC),
        )

    def record_recovery_outcome(
        self, scope: ScopeContext, case_id: UUID, payload: RecoveryOutcomeCreate
    ) -> RecoveryOutcomeRead | None:
        self.last_scope = scope
        if case_id != CASE_ID:
            return None
        outcome_id = uuid4()
        self.recorded_outcomes[outcome_id] = scope.subject
        return RecoveryOutcomeRead(
            outcome_id=outcome_id,
            case_id=case_id,
            amount=payload.amount,
            currency=payload.currency,
            outcome=payload.outcome,
            recorded_by=scope.subject,
            recorded_at=datetime.now(UTC),
        )

    def verify_recovery_outcome(
        self, scope: ScopeContext, outcome_id: UUID, payload: RecoveryVerificationCreate
    ) -> RecoveryVerificationRead | None:
        self.last_scope = scope
        recorder = self.recorded_outcomes.get(outcome_id)
        if recorder is None:
            return None
        if recorder == scope.subject:
            raise HTTPException(status_code=409, detail="Recorder cannot verify own outcome")
        return RecoveryVerificationRead(
            verification_id=uuid4(),
            outcome_id=outcome_id,
            verifier_subject=scope.subject,
            evidence_reference=payload.evidence_reference,
            reason=payload.reason,
            verified_at=datetime.now(UTC),
        )


@pytest.fixture
def client() -> Iterator[TestClient]:
    repository = FakeRepository()
    principal = AuthenticatedPrincipal(
        subject="test-user-01",
        tenant_id=TENANT_A,
        business_unit_id=BU_A1,
        roles=frozenset(
            {
                "revenue_analyst",
                "revenue_investigator",
                "revenue_reviewer",
                "revenue_approver",
                "finance_operator",
                "finance_verifier",
            }
        ),
    )
    app.state.revenue_assurance_repository = repository
    app.state.human_session_issuer = None
    app.dependency_overrides[get_current_principal] = lambda: principal
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    app.state.revenue_assurance_repository = None
    app.state.database_session_broker = None



class FakeHumanSessionIssuer:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[AuthenticatedPrincipal, str]] = []

    def create_session(
        self, *, principal: AuthenticatedPrincipal, broker_token: str
    ) -> HumanDatabaseSessionLease:
        self.calls.append((principal, broker_token))
        if self.error is not None:
            raise self.error
        return HumanDatabaseSessionLease(
            session_id=uuid4(),
            database_role="pwr_finance_user_17",
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
        )


def _database_session_request() -> dict[str, str]:
    return {"broker_token": "signed-customer-step-up-token"}


def _principal_with_issuer() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject="test-user-01",
        tenant_id=TENANT_A,
        business_unit_id=BU_A1,
        roles=frozenset({"finance_verifier"}),
        issuer=ISSUER,
    )


def test_database_session_endpoint_returns_non_secret_lease(
    client: TestClient,
) -> None:
    issuer = FakeHumanSessionIssuer()
    app.state.human_session_issuer = issuer
    app.dependency_overrides[get_current_principal] = _principal_with_issuer

    response = client.post(
        "/api/v1/revenue/database-sessions",
        json=_database_session_request(),
    )

    assert response.status_code == 201
    assert response.json()["database_role"] == "pwr_finance_user_17"
    assert "certificate_pem" not in response.json()
    assert "private_key_pem" not in response.json()
    assert issuer.calls == [
        (_principal_with_issuer(), "signed-customer-step-up-token")
    ]


def test_database_session_endpoint_fails_closed_without_server_issuer(
    client: TestClient,
) -> None:
    app.state.human_session_issuer = None
    app.dependency_overrides[get_current_principal] = _principal_with_issuer

    response = client.post(
        "/api/v1/revenue/database-sessions",
        json=_database_session_request(),
    )

    assert response.status_code == 503


def test_database_session_endpoint_maps_replayed_assertion_to_conflict(
    client: TestClient,
) -> None:
    app.state.human_session_issuer = FakeHumanSessionIssuer(
        error=BrokerReplayError("already consumed")
    )
    app.dependency_overrides[get_current_principal] = _principal_with_issuer

    response = client.post(
        "/api/v1/revenue/database-sessions",
        json=_database_session_request(),
    )

    assert response.status_code == 409


def test_database_session_endpoint_requires_finance_verifier_role(
    client: TestClient,
) -> None:
    app.state.human_session_issuer = FakeHumanSessionIssuer()
    app.dependency_overrides[get_current_principal] = lambda: AuthenticatedPrincipal(
        subject="analyst-01",
        tenant_id=TENANT_A,
        business_unit_id=BU_A1,
        roles=frozenset({"revenue_analyst"}),
        issuer=ISSUER,
    )

    response = client.post(
        "/api/v1/revenue/database-sessions",
        json=_database_session_request(),
    )

    assert response.status_code == 403


def test_list_findings_uses_authenticated_scope(client: TestClient) -> None:
    response = client.get("/api/v1/revenue/findings?category=billing_gap")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert app.state.revenue_assurance_repository.last_scope == ScopeContext(
        tenant_id=TENANT_A,
        business_unit_id=BU_A1,
        subject="test-user-01",
    )


def test_request_cannot_override_tenant_or_business_unit(client: TestClient) -> None:
    # Exercise the real dependency directly: the fixture overrides this
    # dependency for ordinary route tests, which would otherwise bypass it.
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/revenue/findings",
            "raw_path": b"/api/v1/revenue/findings",
            "query_string": (
                b"tenant_id=bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
                b"&business_unit_id=a2000000-0000-4000-8000-000000000002"
            ),
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )
    with pytest.raises(HTTPException) as exc_info:
        get_current_principal(request)
    assert exc_info.value.status_code == 422


def test_case_payload_rejects_client_supplied_scope(client: TestClient) -> None:
    response = client.post(
        "/api/v1/revenue/cases",
        json={
            "finding_id": str(FINDING_ID),
            "summary": "Review missing billing record",
            "reason": "Valid synthetic meter reads have no matching bill.",
            "tenant_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        },
    )
    assert response.status_code == 422


def test_create_case_contract(client: TestClient) -> None:
    response = client.post(
        "/api/v1/revenue/cases",
        json={
            "finding_id": str(FINDING_ID),
            "summary": "Review missing billing record",
            "reason": "Valid synthetic meter reads have no matching bill.",
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "open"


def test_approval_succeeds_with_approver_role(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/revenue/cases/{CASE_ID}/decisions",
        json={"decision": "approve", "reason": "Evidence reviewed and validated."},
    )
    assert response.status_code == 200


def test_recovery_recording_and_verification_are_separate(client: TestClient) -> None:
    recorded = client.post(
        f"/api/v1/revenue/cases/{CASE_ID}/recovery-outcomes",
        json={
            "amount": "1000.2500",
            "currency": "NGN",
            "outcome": "reported",
            "evidence_reference": "bank-receipt-123",
        },
    )
    assert recorded.status_code == 201
    assert recorded.json()["outcome"] == "reported"

    outcome_id = UUID(recorded.json()["outcome_id"])
    app.dependency_overrides[get_current_principal] = lambda: AuthenticatedPrincipal(
        subject="independent-verifier-02",
        tenant_id=TENANT_A,
        business_unit_id=BU_A1,
        roles=frozenset({"finance_verifier"}),
    )
    verified = client.post(
        f"/api/v1/revenue/recovery-outcomes/{outcome_id}/verification",
        json={
            "evidence_reference": "independent-bank-confirmation",
            "reason": "Independent settlement evidence reconciled.",
        },
    )
    assert verified.status_code == 201
    assert verified.json()["verifier_subject"] == "independent-verifier-02"


def test_recovery_recorder_cannot_verify_own_outcome(client: TestClient) -> None:
    recorded = client.post(
        f"/api/v1/revenue/cases/{CASE_ID}/recovery-outcomes",
        json={
            "amount": "1000.2500",
            "currency": "NGN",
            "outcome": "reported",
            "evidence_reference": "bank-receipt-123",
        },
    )
    outcome_id = UUID(recorded.json()["outcome_id"])
    response = client.post(
        f"/api/v1/revenue/recovery-outcomes/{outcome_id}/verification",
        json={
            "evidence_reference": "same-actor-evidence",
            "reason": "Attempted self-verification must fail.",
        },
    )
    assert response.status_code == 409


def test_verified_outcome_cannot_be_submitted_directly(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/revenue/cases/{CASE_ID}/recovery-outcomes",
        json={
            "amount": "1000.2500",
            "currency": "NGN",
            "outcome": "verified",
            "evidence_reference": "bank-receipt-123",
        },
    )
    assert response.status_code == 422


def test_unknown_finding_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/revenue/findings/{uuid4()}")
    assert response.status_code == 404


def test_missing_authenticated_principal_fails_closed() -> None:
    previous = app.state.jwt_verifier
    app.state.jwt_verifier = object()
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/api/v1/revenue/findings")
        assert response.status_code == 401
    finally:
        app.state.jwt_verifier = previous


def test_missing_repository_fails_closed(client: TestClient) -> None:
    app.state.revenue_assurance_repository = None
    response = client.get("/api/v1/revenue/findings")
    assert response.status_code == 503



def test_approval_is_denied_without_approver_role(client: TestClient) -> None:
    app.dependency_overrides[get_current_principal] = lambda: AuthenticatedPrincipal(
        subject="analyst-01",
        tenant_id=TENANT_A,
        business_unit_id=BU_A1,
        roles=frozenset({"revenue_analyst"}),
    )
    response = client.post(
        f"/api/v1/revenue/cases/{CASE_ID}/decisions",
        json={"decision": "approve", "reason": "Evidence reviewed and validated."},
    )
    assert response.status_code == 403
