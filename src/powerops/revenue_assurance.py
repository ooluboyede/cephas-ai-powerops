"""Revenue Assurance API contracts and fail-closed service boundary.

Persistence is injected through a repository adapter. The default application does
not silently fall back to an in-memory store or trust tenant identifiers supplied
by an HTTP caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from powerops.auth import AuthenticatedPrincipal, get_current_principal


@dataclass(frozen=True, slots=True)
class ScopeContext:
    """Server-derived scope passed to every repository operation."""

    tenant_id: UUID
    business_unit_id: UUID
    subject: str


class FindingRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: UUID
    category: str
    status: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    estimated_exposure: Decimal = Field(ge=0)
    evidence_summary: str
    observed_at: datetime


class FindingPage(BaseModel):
    items: list[FindingRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: UUID
    summary: str = Field(min_length=5, max_length=200)
    reason: str = Field(min_length=10, max_length=2000)


class CaseRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: UUID
    finding_id: UUID
    status: str
    created_by: str
    created_at: datetime


class DecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern=r"^(approve|reject|request_more_evidence)$")
    reason: str = Field(min_length=10, max_length=2000)


class DecisionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    case_id: UUID
    decision: str
    actor_subject: str
    reason: str
    decided_at: datetime


class RecoveryOutcomeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    outcome: str = Field(pattern=r"^(reported|reversed|disputed)$")
    evidence_reference: str = Field(min_length=3, max_length=240)


class RecoveryVerificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_reference: str = Field(min_length=3, max_length=240)
    reason: str = Field(min_length=10, max_length=2000)


class RecoveryVerificationRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: UUID
    outcome_id: UUID
    verifier_subject: str
    evidence_reference: str
    reason: str
    verified_at: datetime


class RecoveryOutcomeRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome_id: UUID
    case_id: UUID
    amount: Decimal
    currency: str
    outcome: str
    recorded_by: str
    recorded_at: datetime


class RevenueAssuranceRepository(Protocol):
    """Persistence port; implementations must use the scope-bound DB identity."""

    def list_findings(
        self,
        scope: ScopeContext,
        *,
        finding_status: str | None,
        category: str | None,
        limit: int,
        offset: int,
    ) -> FindingPage: ...

    def get_finding(self, scope: ScopeContext, finding_id: UUID) -> FindingRead | None: ...

    def create_case(self, scope: ScopeContext, payload: CaseCreate) -> CaseRead: ...

    def record_decision(
        self, scope: ScopeContext, case_id: UUID, payload: DecisionCreate
    ) -> DecisionRead | None: ...

    def record_recovery_outcome(
        self, scope: ScopeContext, case_id: UUID, payload: RecoveryOutcomeCreate
    ) -> RecoveryOutcomeRead | None: ...

    def verify_recovery_outcome(
        self, scope: ScopeContext, outcome_id: UUID, payload: RecoveryVerificationCreate
    ) -> RecoveryVerificationRead | None: ...


def get_repository(request: Request) -> RevenueAssuranceRepository:
    repository = getattr(request.app.state, "revenue_assurance_repository", None)
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Revenue Assurance persistence is not configured",
        )
    return cast(RevenueAssuranceRepository, repository)


def _scope(principal: AuthenticatedPrincipal) -> ScopeContext:
    return ScopeContext(
        tenant_id=principal.tenant_id,
        business_unit_id=principal.business_unit_id,
        subject=principal.subject,
    )


def _require_any_role(principal: AuthenticatedPrincipal, *roles: str) -> None:
    if principal.roles.isdisjoint(roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated role is not permitted to perform this action",
        )


router = APIRouter(prefix="/api/v1/revenue", tags=["revenue-assurance"])


@router.get("/findings", response_model=FindingPage)
def list_findings(
    finding_status: str | None = Query(default=None, alias="status", max_length=32),
    category: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    repository: RevenueAssuranceRepository = Depends(get_repository),
) -> FindingPage:
    _require_any_role(
        principal,
        "revenue_analyst",
        "revenue_investigator",
        "revenue_reviewer",
        "revenue_approver",
        "finance_operator",
        "finance_verifier",
        "revenue_admin",
    )
    return repository.list_findings(
        _scope(principal),
        finding_status=finding_status,
        category=category,
        limit=limit,
        offset=offset,
    )


@router.get("/findings/{finding_id}", response_model=FindingRead)
def get_finding(
    finding_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    repository: RevenueAssuranceRepository = Depends(get_repository),
) -> FindingRead:
    _require_any_role(
        principal,
        "revenue_analyst",
        "revenue_investigator",
        "revenue_reviewer",
        "revenue_approver",
        "finance_operator",
        "finance_verifier",
        "revenue_admin",
    )
    finding = repository.get_finding(_scope(principal), finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


@router.post("/cases", response_model=CaseRead, status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CaseCreate,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    repository: RevenueAssuranceRepository = Depends(get_repository),
) -> CaseRead:
    _require_any_role(principal, "revenue_investigator", "revenue_admin")
    return repository.create_case(_scope(principal), payload)


@router.post("/cases/{case_id}/decisions", response_model=DecisionRead)
def record_decision(
    case_id: UUID,
    payload: DecisionCreate,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    repository: RevenueAssuranceRepository = Depends(get_repository),
) -> DecisionRead:
    if payload.decision == "approve":
        _require_any_role(principal, "revenue_approver", "revenue_admin")
    else:
        _require_any_role(principal, "revenue_reviewer", "revenue_approver", "revenue_admin")
    decision = repository.record_decision(_scope(principal), case_id, payload)
    if decision is None:
        raise HTTPException(status_code=404, detail="Investigation case not found")
    return decision


@router.post(
    "/cases/{case_id}/recovery-outcomes",
    response_model=RecoveryOutcomeRead,
    status_code=status.HTTP_201_CREATED,
)
def record_recovery_outcome(
    case_id: UUID,
    payload: RecoveryOutcomeCreate,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    repository: RevenueAssuranceRepository = Depends(get_repository),
) -> RecoveryOutcomeRead:
    _require_any_role(principal, "finance_operator", "revenue_admin")
    outcome = repository.record_recovery_outcome(_scope(principal), case_id, payload)
    if outcome is None:
        raise HTTPException(status_code=404, detail="Investigation case not found")
    return outcome


@router.post(
    "/recovery-outcomes/{outcome_id}/verification",
    response_model=RecoveryVerificationRead,
    status_code=status.HTTP_201_CREATED,
)
def verify_recovery_outcome(
    outcome_id: UUID,
    payload: RecoveryVerificationCreate,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    repository: RevenueAssuranceRepository = Depends(get_repository),
) -> RecoveryVerificationRead:
    _require_any_role(principal, "finance_verifier", "revenue_admin")
    verification = repository.verify_recovery_outcome(
        _scope(principal), outcome_id, payload
    )
    if verification is None:
        raise HTTPException(status_code=404, detail="Recovery outcome not found")
    return verification
