from __future__ import annotations

from time import time
from typing import Any
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from powerops.auth import AuthenticatedPrincipal, OidcJwtVerifier
from powerops.main import app


TENANT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BUSINESS_UNIT_ID = UUID("a1000000-0000-4000-8000-000000000001")


class StubJwksClient:
    def __init__(self, key: Any = "public-key") -> None:
        self.key = key

    def get_signing_key_from_jwt(self, token: str) -> Any:
        if self.key == "public-key":
            assert token == "signed.jwt.token"
        return type("SigningKey", (), {"key": self.key})()


class StubVerifier:
    def verify(self, token: str) -> AuthenticatedPrincipal:
        if token != "valid-token":
            raise ValueError("invalid token")
        return AuthenticatedPrincipal(
            subject="oidc-user-123",
            tenant_id=TENANT_ID,
            business_unit_id=BUSINESS_UNIT_ID,
            roles=frozenset({"revenue_analyst"}),
        )


def test_oidc_verifier_pins_algorithm_issuer_audience_and_required_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = OidcJwtVerifier(
        issuer="https://identity.example.com/",
        audience="powerops-api",
        jwks_url="https://identity.example.com/.well-known/jwks.json",
    )
    verifier.jwks_client = StubJwksClient()  # type: ignore[assignment]
    claims: dict[str, Any] = {
        "sub": "oidc-user-123",
        "iss": "https://identity.example.com/",
        "aud": "powerops-api",
        "exp": 2_000_000_000,
        "iat": 1_900_000_000,
        "tenant_id": str(TENANT_ID),
        "business_unit_id": str(BUSINESS_UNIT_ID),
        "roles": ["revenue_analyst"],
    }
    captured: dict[str, Any] = {}

    def fake_decode(token: str, key: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        assert token == "signed.jwt.token"
        assert key == "public-key"
        return claims

    monkeypatch.setattr(jwt, "decode", fake_decode)
    principal = verifier.verify("signed.jwt.token")

    assert principal.subject == "oidc-user-123"
    assert principal.tenant_id == TENANT_ID
    assert principal.business_unit_id == BUSINESS_UNIT_ID
    assert principal.roles == frozenset({"revenue_analyst"})
    assert captured["algorithms"] == ["RS256"]
    assert captured["issuer"] == "https://identity.example.com/"
    assert captured["audience"] == "powerops-api"
    assert set(captured["options"]["require"]) == {"exp", "iat", "sub", "iss", "aud"}


def test_oidc_verifier_rejects_missing_scope_and_role_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = OidcJwtVerifier(
        issuer="https://identity.example.com",
        audience="powerops-api",
        jwks_url="https://identity.example.com/jwks",
    )
    verifier.jwks_client = StubJwksClient()  # type: ignore[assignment]
    monkeypatch.setattr(
        jwt,
        "decode",
        lambda *args, **kwargs: {
            "sub": "oidc-user-123",
            "tenant_id": str(TENANT_ID),
            "business_unit_id": str(BUSINESS_UNIT_ID),
            "roles": "revenue_analyst",
        },
    )
    with pytest.raises(ValueError):
        verifier.verify("signed.jwt.token")


def test_revenue_endpoint_requires_bearer_token() -> None:
    previous = app.state.jwt_verifier
    app.state.jwt_verifier = StubVerifier()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/revenue/findings")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
    finally:
        app.state.jwt_verifier = previous


def test_revenue_endpoint_derives_scope_from_verified_token() -> None:
    previous_verifier = app.state.jwt_verifier
    previous_repository = app.state.revenue_assurance_repository
    app.state.jwt_verifier = StubVerifier()
    app.state.revenue_assurance_repository = None
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/revenue/findings",
                headers={"Authorization": "Bearer valid-token"},
            )
        # Authentication succeeds; persistence then fails closed because it is not configured.
        assert response.status_code == 503
        assert response.json()["detail"] == "Revenue Assurance persistence is not configured"
    finally:
        app.state.jwt_verifier = previous_verifier
        app.state.revenue_assurance_repository = previous_repository


def test_oidc_not_configured_fails_closed() -> None:
    previous = app.state.jwt_verifier
    app.state.jwt_verifier = None
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/revenue/findings",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert response.status_code == 503
        assert response.json()["detail"] == "OIDC authentication is not configured"
    finally:
        app.state.jwt_verifier = previous


def test_tenant_scope_query_override_is_rejected_even_with_bearer() -> None:
    previous = app.state.jwt_verifier
    app.state.jwt_verifier = StubVerifier()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/revenue/findings?tenant_id=bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert response.status_code == 422
    finally:
        app.state.jwt_verifier = previous


def test_oidc_settings_must_be_configured_as_a_complete_set() -> None:
    from pydantic import ValidationError

    from powerops.config import Settings

    with pytest.raises(ValidationError):
        Settings(oidc_issuer="https://identity.example.com")


def test_oidc_settings_reject_insecure_nonlocal_urls() -> None:
    from pydantic import ValidationError

    from powerops.config import Settings

    with pytest.raises(ValidationError):
        Settings(
            oidc_issuer="http://identity.example.com",
            oidc_audience="powerops-api",
            oidc_jwks_url="http://identity.example.com/jwks",
        )


def test_oidc_settings_accept_https_provider_configuration() -> None:
    from powerops.config import Settings

    settings = Settings(
        oidc_issuer="https://identity.example.com/",
        oidc_audience="powerops-api",
        oidc_jwks_url="https://identity.example.com/.well-known/jwks.json",
    )
    assert settings.oidc_issuer == "https://identity.example.com/"
    assert settings.oidc_audience == "powerops-api"


def test_jwks_connection_failure_returns_service_unavailable() -> None:
    from urllib.error import URLError

    class UnavailableVerifier:
        def verify(self, token: str) -> AuthenticatedPrincipal:
            raise URLError("identity provider unavailable")

    previous = app.state.jwt_verifier
    app.state.jwt_verifier = UnavailableVerifier()
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/revenue/findings",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert response.status_code == 503
    finally:
        app.state.jwt_verifier = previous


def test_oidc_verifier_cryptographically_checks_rs256_signature() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = OidcJwtVerifier(
        issuer="https://identity.example.com",
        audience="powerops-api",
        jwks_url="https://identity.example.com/jwks",
    )
    verifier.jwks_client = StubJwksClient(private_key.public_key())  # type: ignore[assignment]
    now = int(time())
    claims = {
        "sub": "oidc-user-123",
        "iss": "https://identity.example.com",
        "aud": "powerops-api",
        "exp": now + 300,
        "iat": now - 1,
        "tenant_id": str(TENANT_ID),
        "business_unit_id": str(BUSINESS_UNIT_ID),
        "roles": ["revenue_analyst"],
    }
    valid_token = jwt.encode(claims, private_key, algorithm="RS256")
    invalid_token = jwt.encode(claims, other_private_key, algorithm="RS256")

    assert verifier.verify(valid_token).subject == "oidc-user-123"
    with pytest.raises(jwt.InvalidSignatureError):
        verifier.verify(invalid_token)
