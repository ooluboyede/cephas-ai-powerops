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


@dataclass(frozen=True, slots=True)
class StoredHumanSessionCredential:
    """Decrypted session material returned transiently by a customer vault.

    Instances are short-lived application data, not a persistence format. A
    concrete store must never expose this object outside the trusted server
    process or serialize its private-key field into logs or API responses.
    """

    session_id: UUID
    issuer: str
    subject: str
    tenant_id: UUID
    business_unit_id: UUID
    finance_operator: bool
    finance_verifier: bool
    database_role: str
    certificate_pem: str
    private_key_pem: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, UUID):
            raise ValueError("Credential session_id must be a UUID")
        if not self.issuer.startswith("https://") or not self.subject.strip():
            raise ValueError("Credential issuer and subject must identify a verified actor")
        if not isinstance(self.tenant_id, UUID) or not isinstance(self.business_unit_id, UUID):
            raise ValueError("Credential tenant and business-unit identifiers must be UUIDs")
        if self.finance_operator == self.finance_verifier:
            raise ValueError("Exactly one finance entitlement must be stored")
        if not re.fullmatch(r"pwr_[a-z0-9_]{1,40}", self.database_role):
            raise ValueError("Credential database role is invalid")
        if not self.certificate_pem.startswith("-----BEGIN CERTIFICATE-----"):
            raise ValueError("Credential certificate must be PEM encoded")
        if not self.private_key_pem.startswith("-----BEGIN PRIVATE KEY-----"):
            raise ValueError("Credential private key must be unencrypted PKCS8 PEM")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("Credential expiry must be timezone-aware")


class HumanSessionCredentialConflict(RuntimeError):
    """The session UUID is already bound to a different immutable credential."""


class HumanSessionCredentialStoreUnavailable(RuntimeError):
    """The customer credential store cannot safely complete the requested operation."""


class HumanSessionCredentialStore(Protocol):
    """Customer-controlled, encrypted store for short-lived human DB credentials.

    Contract requirements for every implementation:

    * store_session is an atomic CREATE operation keyed by the exact session UUID.
      It must never silently replace an existing record.
    * Repeating a write for the same UUID and identical complete record is
      idempotent. Reusing that UUID for any different actor, scope, role,
      entitlement, certificate, key or expiry raises
      HumanSessionCredentialConflict.
    * The record is stored as one indivisible unit. Partial writes must not be
      observable through get_session.
    * Private keys are encrypted at rest by customer-controlled key management;
      access is least-privilege and audited. The application identity cannot
      administer the vault, policies, mounts or CA.
    * get_session performs an exact UUID lookup only. It must not list, search,
      or fall back to another session, tenant, business unit or shared
      credential. Expired and revoked records return None.
    * Implementations enforce expiry at read time and apply a TTL no later than
      the credential expiry. Revocation prevents subsequent retrieval.
    * No method logs or returns private-key material through diagnostics,
      exception text, telemetry, audit payloads or API responses.
    * Store outages, authentication failures and malformed responses fail
      closed; implementations raise HumanSessionCredentialStoreUnavailable
      (or a safe adapter-specific exception) without including secret values.
    """

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
        """Atomically create an immutable exact-session record. Identical retries are idempotent; conflicting UUID reuse raises HumanSessionCredentialConflict and never overwrites the original record."""

    def get_session(
        self, session_id: UUID
    ) -> StoredHumanSessionCredential | None:
        """Return only the exact active session, or None if absent, expired or revoked; never search or fall back to another session."""


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
