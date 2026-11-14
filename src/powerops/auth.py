"""OIDC/JWT authentication boundary for PowerOps Revenue Assurance.

Only configured issuer keys can authenticate API requests. Tenant, business-unit
and role claims are accepted from the verified token, never from request headers
or request bodies.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient, PyJWTError


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Identity and authorization claims from a cryptographically verified JWT."""

    subject: str
    tenant_id: UUID
    business_unit_id: UUID
    roles: frozenset[str]


class OidcJwtVerifier:
    """Verify RS256 access tokens against a configured OIDC JWKS endpoint."""

    def __init__(self, *, issuer: str, audience: str, jwks_url: str) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.jwks_client = PyJWKClient(
            jwks_url,
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
        )

    def verify(self, token: str) -> AuthenticatedPrincipal:
        signing_key = self.jwks_client.get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self.audience,
            issuer=self.issuer,
            leeway=30,
            options={
                "require": ["exp", "iat", "sub", "iss", "aud"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
        subject = claims.get("sub")
        tenant_claim = claims.get("tenant_id")
        business_unit_claim = claims.get("business_unit_id")
        roles_claim = claims.get("roles")
        if (
            not isinstance(subject, str)
            or not subject.strip()
            or not isinstance(tenant_claim, str)
            or not isinstance(business_unit_claim, str)
            or not isinstance(roles_claim, list)
            or not roles_claim
            or any(not isinstance(role, str) or not role.strip() for role in roles_claim)
        ):
            raise ValueError("Required identity and authorization claims are missing")
        return AuthenticatedPrincipal(
            subject=subject,
            tenant_id=UUID(tenant_claim),
            business_unit_id=UUID(business_unit_claim),
            roles=frozenset(roles_claim),
        )


def get_current_principal(request: Request) -> AuthenticatedPrincipal:
    """Authenticate a bearer token and derive scope exclusively from verified claims."""
    if any(key in request.query_params for key in ("tenant_id", "business_unit_id")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tenant and business-unit scope must come from authenticated identity",
        )

    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC authentication is not configured",
        )

    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return verifier.verify(token.strip())
    except (PyJWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
