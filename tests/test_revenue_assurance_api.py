from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

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
    ScopeContext,
    get_current_principal,
)

TENANT_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BU_A1 = UUID("a1000000-0000-4000-8000-000000000001")
FINDING_ID = UUID("d1000000-0000-4000-8000-000000000001")
CASE_ID = UUID("f1000000-0000-4000-8000-000000000001")


class FakeRepository:
    def __init__(self) -> None:
        self.last_scope: ScopeContext | None = None

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
        return RecoveryOutcomeRead(
            outcome_id=uuid4(),
            case_id=case_id,
            amount=payload.amount,
            currency=payload.currency,
            outcome=payload.outcome,
            recorded_by=scope.subject,
            recorded_at=datetime.now(UTC),
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
    app.dependency_overrides[get_current_principal] = lambda: principal
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    app.state.revenue_assurance_repository = None


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
    response = client.get(
        "/api/v1/revenue/findings",
        params={
            "tenant_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "business_unit_id": str(uuid4()),
        },
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert app.state.revenue_assurance_repository.last_scope == ScopeContext(
        tenant_id=TENANT_A,
        business_unit_id=BU_A1,
        subject="test-user-01",
    )


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


def test_approval_requires_approver_role(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/revenue/cases/{CASE_ID}/decisions",
        json={"decision": "approve", "reason": "Evidence reviewed and validated."},
    )
    assert response.status_code == 200


def test_verified_recovery_contract(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/revenue/cases/{CASE_ID}/recovery-outcomes",
        json={
            "amount": "1000.2500",
            "currency": "NGN",
            "outcome": "verified",
            "evidence_reference": "bank-receipt-123",
        },
    )
    assert response.status_code == 201
    assert response.json()["outcome"] == "verified"


def test_unknown_finding_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/revenue/findings/{uuid4()}")
    assert response.status_code == 404


def test_missing_authenticated_principal_fails_closed() -> None:
    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/revenue/findings")
    assert response.status_code == 401


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
