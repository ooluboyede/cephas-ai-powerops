"""Customer-operated identity broker core for human PostgreSQL sessions.

This module is deliberately separate from the PowerOps API and shared BU pool.
It defines a fail-closed broker service with injected customer directory,
atomic replay guard and customer-controlled certificate signer. No CA private
key or certificate issuance implementation is included in this package.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.types import PublicKeyTypes
from cryptography.x509.oid import NameOID
from jwt import PyJWKClient, PyJWKClientConnectionError, PyJWTError


class BrokerAuthenticationError(Exception):
    """The customer identity assertion is invalid or insufficient."""


class BrokerAuthorizationError(Exception):
    """The authenticated principal is not entitled to a database session."""


class BrokerReplayError(Exception):
    """The token identifier has already been consumed."""


class BrokerDependencyUnavailable(Exception):
    """A required customer-controlled broker dependency is unavailable."""


@dataclass(frozen=True, slots=True)
class BrokerPolicy:
    """Customer-approved token, assurance and certificate lifetime policy."""

    issuer: str
    audience: str
    jwks_url: str
    allowed_acrs: frozenset[str]
    required_amr: frozenset[str] = frozenset({"mfa"})
    max_token_age_seconds: int = 300
    max_step_up_age_seconds: int = 300
    certificate_ttl_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.issuer or not self.audience or not self.jwks_url.startswith("https://"):
            raise ValueError("Broker issuer, audience and HTTPS JWKS URL are required")
        if not self.allowed_acrs:
            raise ValueError("At least one customer-approved authentication context is required")
        if not 1 <= self.max_token_age_seconds <= 900:
            raise ValueError("Maximum token age must be between 1 and 900 seconds")
        if not 1 <= self.max_step_up_age_seconds <= 900:
            raise ValueError("Maximum step-up age must be between 1 and 900 seconds")
        if not 1 <= self.certificate_ttl_seconds <= 300:
            raise ValueError("Client certificate lifetime must be between 1 and 300 seconds")


@dataclass(frozen=True, slots=True)
class BrokerPrincipal:
    """Claims validated from the signed broker-audience customer token."""

    issuer: str
    subject: str
    tenant_id: UUID
    business_unit_id: UUID
    roles: frozenset[str]
    jti: str
    issued_at: datetime
    expires_at: datetime
    authentication_time: datetime
    acr: str
    amr: frozenset[str]


@dataclass(frozen=True, slots=True)
class DatabasePrincipal:
    """Customer-directory record; never constructed from API-supplied role data."""

    issuer: str
    subject: str
    tenant_id: UUID
    business_unit_id: UUID
    database_role: str
    active: bool
    finance_verifier: bool


@dataclass(frozen=True, slots=True)
class IssuedDatabaseSession:
    """Public session material returned to the authenticated workload."""

    certificate_pem: str
    expires_at: datetime
    database_role: str
    session_id: UUID


class BrokerTokenVerifier(Protocol):
    def verify(self, token: str, *, now: datetime) -> BrokerPrincipal:
        """Validate the customer assertion independently of the API tier."""


class IdentityDirectory(Protocol):
    def resolve(
        self, issuer: str, subject: str, tenant_id: UUID, business_unit_id: UUID
    ) -> DatabasePrincipal | None:
        """Resolve an active, pre-provisioned human database identity."""


class AtomicReplayGuard(Protocol):
    def consume(self, jti: str, csr_fingerprint: str, expires_at: datetime) -> bool:
        """Atomically consume a token ID; return False if it was already consumed."""


class CustomerCertificateIssuer(Protocol):
    def issue(
        self,
        *,
        database_role: str,
        issuer: str,
        subject: str,
        tenant_id: UUID,
        business_unit_id: UUID,
        public_key: PublicKeyTypes,
        expires_at: datetime,
    ) -> str:
        """Sign a role-bound certificate using a customer-controlled CA/HSM."""

    def verify_issued_certificate(
        self,
        certificate_pem: str,
        *,
        database_role: str,
        public_key: PublicKeyTypes,
        expires_at: datetime,
        now: datetime,
    ) -> bool:
        """Verify the certificate signature and chain against customer trust anchors."""


class OidcBrokerTokenVerifier:
    """Validate RS256 broker-audience tokens against the customer's OIDC JWKS."""

    def __init__(self, policy: BrokerPolicy) -> None:
        self._policy = policy
        self._jwks = PyJWKClient(
            policy.jwks_url, cache_jwk_set=True, lifespan=60, timeout=5
        )

    def verify(self, token: str, *, now: datetime) -> BrokerPrincipal:
        if now.tzinfo is None:
            raise ValueError("Broker clock must be timezone-aware")
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._policy.audience,
                issuer=self._policy.issuer,
                leeway=5,
                options={
                    "require": ["iss", "aud", "sub", "iat", "exp", "jti"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except (PyJWKClientConnectionError, TimeoutError, OSError) as exc:
            raise BrokerDependencyUnavailable("Customer JWKS is unavailable") from exc
        except (PyJWTError, ValueError, TypeError) as exc:
            raise BrokerAuthenticationError("Customer broker token is invalid") from exc

        subject = claims.get("sub")
        jti = claims.get("jti")
        tenant_claim = claims.get("tenant_id")
        business_unit_claim = claims.get("business_unit_id")
        roles_claim = claims.get("roles")
        acr = claims.get("acr")
        amr_claim = claims.get("amr")
        auth_time = claims.get("auth_time")
        issued_at = claims.get("iat")
        expires_at = claims.get("exp")
        if (
            not isinstance(subject, str) or not subject.strip() or len(subject) > 200
            or not isinstance(jti, str) or not jti.strip() or len(jti) > 512
            or not isinstance(tenant_claim, str)
            or not isinstance(business_unit_claim, str)
            or not isinstance(roles_claim, list)
            or any(not isinstance(role, str) or not role.strip() for role in roles_claim)
            or not isinstance(acr, str)
            or not isinstance(amr_claim, list)
            or any(not isinstance(method, str) for method in amr_claim)
            or not isinstance(auth_time, int)
            or not isinstance(issued_at, int)
            or not isinstance(expires_at, int)
        ):
            raise BrokerAuthenticationError("Required broker identity claims are missing")

        current = now.astimezone(UTC)
        try:
            issued = datetime.fromtimestamp(issued_at, UTC)
            expires = datetime.fromtimestamp(expires_at, UTC)
            authenticated = datetime.fromtimestamp(auth_time, UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise BrokerAuthenticationError(
                "Broker token time claim is outside the supported range"
            ) from exc
        if expires <= issued or (expires - issued).total_seconds() > 900:
            raise BrokerAuthenticationError("Broker token lifetime exceeds customer policy")
        if (current - issued).total_seconds() > self._policy.max_token_age_seconds:
            raise BrokerAuthenticationError("Broker token exceeds the permitted age")
        if issued > current + timedelta(seconds=5):
            raise BrokerAuthenticationError("Broker token issue time is in the future")
        if authenticated > current + timedelta(seconds=5):
            raise BrokerAuthenticationError("Authentication time is in the future")
        if (current - authenticated).total_seconds() > self._policy.max_step_up_age_seconds:
            raise BrokerAuthenticationError("Finance step-up authentication is too old")
        if acr not in self._policy.allowed_acrs:
            raise BrokerAuthenticationError("Customer authentication context is insufficient")
        if not self._policy.required_amr.issubset(set(amr_claim)):
            raise BrokerAuthenticationError("Required MFA method is absent")

        try:
            tenant_id = UUID(tenant_claim)
            business_unit_id = UUID(business_unit_claim)
        except ValueError as exc:
            raise BrokerAuthenticationError("Tenant or business-unit claim is invalid") from exc

        return BrokerPrincipal(
            issuer=self._policy.issuer,
            subject=subject,
            tenant_id=tenant_id,
            business_unit_id=business_unit_id,
            roles=frozenset(roles_claim),
            jti=jti,
            issued_at=issued,
            expires_at=expires,
            authentication_time=authenticated,
            acr=acr,
            amr=frozenset(amr_claim),
        )


class DatabaseSessionBroker:
    """Issue short-lived, role-bound database certificates after independent checks."""

    _ROLE_PATTERN = re.compile(r"^pwr_[a-z0-9_]{1,40}$")

    def __init__(
        self,
        *,
        policy: BrokerPolicy,
        token_verifier: BrokerTokenVerifier,
        directory: IdentityDirectory,
        replay_guard: AtomicReplayGuard,
        certificate_issuer: CustomerCertificateIssuer,
    ) -> None:
        self._policy = policy
        self._token_verifier = token_verifier
        self._directory = directory
        self._replay_guard = replay_guard
        self._certificate_issuer = certificate_issuer

    @staticmethod
    def _validated_csr(csr_pem: str) -> tuple[PublicKeyTypes, str]:
        if len(csr_pem) > 16_384:
            raise BrokerAuthenticationError("CSR exceeds the permitted size")
        try:
            csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise BrokerAuthenticationError("CSR is not valid PEM") from exc
        if not csr.is_signature_valid:
            raise BrokerAuthenticationError("CSR proof-of-possession signature is invalid")

        public_key = csr.public_key()
        if isinstance(public_key, rsa.RSAPublicKey):
            if public_key.key_size < 3072:
                raise BrokerAuthenticationError("RSA CSR keys must be at least 3072 bits")
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            if public_key.curve.name not in {"secp256r1", "secp384r1"}:
                raise BrokerAuthenticationError("EC CSR curve is not approved")
        else:
            raise BrokerAuthenticationError("CSR public-key type is not approved")

        public_der = public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return public_key, hashlib.sha256(public_der).hexdigest()

    def issue_session(
        self, *, token: str, csr_pem: str, now: datetime | None = None
    ) -> IssuedDatabaseSession:
        supplied_now = now or datetime.now(UTC)
        if supplied_now.tzinfo is None:
            raise ValueError("Broker clock must be timezone-aware")
        current = supplied_now.astimezone(UTC)

        principal = self._token_verifier.verify(token, now=current)
        if "finance_verifier" not in principal.roles:
            raise BrokerAuthorizationError("Finance-verifier entitlement is required")

        try:
            database_principal = self._directory.resolve(
                principal.issuer,
                principal.subject,
                principal.tenant_id,
                principal.business_unit_id,
            )
        except Exception as exc:
            raise BrokerDependencyUnavailable(
                "Customer identity directory is unavailable"
            ) from exc
        if database_principal is None or not database_principal.active:
            raise BrokerAuthorizationError("No active customer database identity exists")
        if (
            database_principal.issuer != principal.issuer
            or database_principal.subject != principal.subject
            or database_principal.tenant_id != principal.tenant_id
            or database_principal.business_unit_id != principal.business_unit_id
            or not database_principal.finance_verifier
        ):
            raise BrokerAuthorizationError(
                "Customer database identity scope or entitlement mismatch"
            )
        if not self._ROLE_PATTERN.fullmatch(database_principal.database_role):
            raise BrokerAuthorizationError("Customer directory returned an invalid database role")

        public_key, fingerprint = self._validated_csr(csr_pem)
        certificate_expiry = min(
            principal.expires_at,
            current + timedelta(seconds=self._policy.certificate_ttl_seconds),
        )
        if certificate_expiry <= current:
            raise BrokerAuthenticationError("No valid certificate lifetime remains")

        # Consume before signing. A signing failure requires a fresh token; the
        # broker never retries a consumed assertion with an untracked issuance.
        try:
            consumed = self._replay_guard.consume(
                principal.jti, fingerprint, certificate_expiry
            )
        except Exception as exc:
            raise BrokerDependencyUnavailable("Customer replay guard is unavailable") from exc
        if not consumed:
            raise BrokerReplayError("Broker token identifier has already been consumed")

        try:
            certificate_pem = self._certificate_issuer.issue(
                database_role=database_principal.database_role,
                issuer=principal.issuer,
                subject=principal.subject,
                tenant_id=principal.tenant_id,
                business_unit_id=principal.business_unit_id,
                public_key=public_key,
                expires_at=certificate_expiry,
            )
        except Exception as exc:
            raise BrokerDependencyUnavailable(
                "Customer certificate issuer failed; request a fresh broker token"
            ) from exc

        if not isinstance(certificate_pem, str) or "BEGIN CERTIFICATE" not in certificate_pem:
            raise BrokerDependencyUnavailable(
                "Customer certificate issuer returned invalid material"
            )
        try:
            certificate = x509.load_pem_x509_certificate(certificate_pem.encode("ascii"))
            issued_public_key = certificate.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            requested_public_key = public_key.public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            common_names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            if (
                not self._certificate_issuer.verify_issued_certificate(
                    certificate_pem,
                    database_role=database_principal.database_role,
                    public_key=public_key,
                    expires_at=certificate_expiry,
                    now=current,
                )
                or issued_public_key != requested_public_key
                or len(common_names) != 1
                or common_names[0].value != database_principal.database_role
                or certificate.not_valid_before_utc > current
                or certificate.not_valid_after_utc > certificate_expiry
                or certificate.not_valid_after_utc <= current
            ):
                raise ValueError("Issued certificate does not match the approved session")
        except Exception as exc:
            raise BrokerDependencyUnavailable(
                "Customer certificate issuer returned an unbound or invalid certificate"
            ) from exc

        return IssuedDatabaseSession(
            certificate_pem=certificate_pem,
            expires_at=certificate_expiry,
            database_role=database_principal.database_role,
            session_id=uuid4(),
        )
