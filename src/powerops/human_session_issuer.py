"""Server-side issuance and storage of human PostgreSQL session credentials.

The browser never receives the PostgreSQL certificate or private key. The API
creates the keypair/CSR, asks the customer broker for a certificate, validates
the broker identity against the API principal, and stores both materials using
an injected customer-controlled credential store.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID
import re

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from powerops.auth import AuthenticatedPrincipal
from powerops.identity_broker import (
    BrokerAuthenticationError,
    BrokerAuthorizationError,
    BrokerDependencyUnavailable,
    IssuedDatabaseSession,
)


@dataclass(frozen=True, slots=True)
class HumanDatabaseSessionLease:
    """Non-secret session handle returned to the authenticated API client."""

    session_id: UUID
    database_role: str
    expires_at: datetime


class HumanSessionBroker(Protocol):
    """Customer-operated broker that signs a CSR for a provisioned human role."""

    def issue_session(self, *, token: str, csr_pem: str) -> IssuedDatabaseSession:
        """Validate the broker token and return a short-lived role-bound certificate."""


class HumanSessionCredentialStore(Protocol):
    """Customer-controlled store for session certificates and private keys."""

    def store_session(
        self,
        *,
        session_id: UUID,
        issuer: str,
        subject: str,
        tenant_id: UUID,
        business_unit_id: UUID,
        finance_operator: bool,
        finance_verifier: bool,
        database_role: str,
        certificate_pem: str,
        private_key_pem: str,
        expires_at: datetime,
    ) -> None:
        """Persist credentials securely; encrypt private keys at rest and enforce TTL."""


class HumanSessionIssuer:
    """Issue a DB session whose private key remains exclusively server-side."""

    _ROLE_PATTERN = re.compile(r"^pwr_[a-z0-9_]{1,40}$")
    _MAX_CERTIFICATE_TTL = timedelta(seconds=300)

    def __init__(
        self,
        *,
        broker: HumanSessionBroker,
        credential_store: HumanSessionCredentialStore,
    ) -> None:
        self._broker = broker
        self._credential_store = credential_store

    @staticmethod
    def _create_key_and_csr() -> tuple[str, str]:
        private_key = ec.generate_private_key(ec.SECP256R1())
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name(
                    [x509.NameAttribute(NameOID.COMMON_NAME, "powerops-human-session")]
                )
            )
            .sign(private_key, hashes.SHA256())
        )
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("ascii")
        private_key_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")
        return csr_pem, private_key_pem

    def create_session(
        self, *, principal: AuthenticatedPrincipal, broker_token: str
    ) -> HumanDatabaseSessionLease:
        """Issue and store credentials; return only a non-secret lease."""
        if not principal.issuer.startswith("https://") or not principal.subject.strip():
            raise BrokerAuthorizationError("A verified OIDC principal is required")
        finance_operator = "finance_operator" in principal.roles
        finance_verifier = "finance_verifier" in principal.roles
        if finance_operator == finance_verifier:
            raise BrokerAuthorizationError(
                "Exactly one finance maker or verifier entitlement is required"
            )
        if not broker_token.strip():
            raise BrokerAuthenticationError("A customer broker token is required")

        csr_pem, private_key_pem = self._create_key_and_csr()
        issued = self._broker.issue_session(token=broker_token, csr_pem=csr_pem)

        if (
            issued.issuer != principal.issuer
            or issued.subject != principal.subject
            or issued.tenant_id != principal.tenant_id
            or issued.business_unit_id != principal.business_unit_id
            or issued.finance_operator is not finance_operator
            or issued.finance_verifier is not finance_verifier
        ):
            raise BrokerAuthorizationError(
                "Broker-issued database identity does not match the API principal"
            )
        if not self._ROLE_PATTERN.fullmatch(issued.database_role):
            raise BrokerAuthorizationError("Broker returned an invalid database role")
        if "BEGIN CERTIFICATE" not in issued.certificate_pem:
            raise BrokerDependencyUnavailable(
                "Customer broker returned invalid certificate material"
            )

        now = datetime.now(UTC)
        if issued.expires_at.tzinfo is None:
            raise BrokerAuthenticationError("Broker certificate expiry must be timezone-aware")
        expiry = issued.expires_at.astimezone(UTC)
        if expiry <= now or expiry > now + self._MAX_CERTIFICATE_TTL:
            raise BrokerAuthenticationError("Broker certificate expiry is outside policy")

        try:
            self._credential_store.store_session(
                session_id=issued.session_id,
                issuer=issued.issuer,
                subject=issued.subject,
                tenant_id=issued.tenant_id,
                business_unit_id=issued.business_unit_id,
                finance_operator=issued.finance_operator,
                finance_verifier=issued.finance_verifier,
                database_role=issued.database_role,
                certificate_pem=issued.certificate_pem,
                private_key_pem=private_key_pem,
                expires_at=expiry,
            )
        except Exception as exc:
            raise BrokerDependencyUnavailable(
                "Customer human-session credential store is unavailable"
            ) from exc

        return HumanDatabaseSessionLease(
            session_id=issued.session_id,
            database_role=issued.database_role,
            expires_at=expiry,
        )
