from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from powerops.identity_broker import (
    BrokerAuthenticationError,
    BrokerAuthorizationError,
    BrokerPolicy,
    BrokerPrincipal,
    BrokerReplayError,
    DatabasePrincipal,
    DatabaseSessionBroker,
)


TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BUSINESS_UNIT = UUID("a1000000-0000-4000-8000-000000000001")
ISSUER = "https://idp.customer.example/"
SUBJECT = "finance-user-001"


class StaticTokenVerifier:
    def __init__(self, principal: BrokerPrincipal) -> None:
        self.principal = principal

    def verify(self, token: str, *, now: datetime) -> BrokerPrincipal:
        assert token == "signed-customer-token"
        return self.principal


class StaticDirectory:
    def __init__(self, principal: DatabasePrincipal | None) -> None:
        self.principal = principal

    def resolve(
        self, issuer: str, subject: str, tenant_id: UUID, business_unit_id: UUID
    ) -> DatabasePrincipal | None:
        assert (issuer, subject, tenant_id, business_unit_id) == (
            ISSUER, SUBJECT, TENANT, BUSINESS_UNIT
        )
        return self.principal


class InMemoryReplayGuard:
    """Test-only atomicity model; production must use a shared durable store."""

    def __init__(self) -> None:
        self.used: set[str] = set()

    def consume(self, jti: str, csr_fingerprint: str, expires_at: datetime) -> bool:
        if jti in self.used:
            return False
        self.used.add(jti)
        return True


class TestCertificateIssuer:
    """Disposable test CA; never use this implementation in customer deployments."""

    def __init__(self) -> None:
        self.ca_key = ec.generate_private_key(ec.SECP256R1())
        self.ca = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-only-ca")]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-only-ca")]))
            .public_key(self.ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC) - timedelta(seconds=5))
            .not_valid_after(datetime.now(UTC) + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(self.ca_key, hashes.SHA256())
        )

    def issue(
        self,
        *,
        database_role: str,
        issuer: str,
        subject: str,
        tenant_id: UUID,
        business_unit_id: UUID,
        public_key: object,
        expires_at: datetime,
    ) -> str:
        certificate = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, database_role)])
            )
            .issuer_name(self.ca.subject)
            .public_key(public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC) - timedelta(seconds=1))
            .not_valid_after(expires_at)
            .sign(self.ca_key, hashes.SHA256())
        )
        return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


def build_fixture() -> tuple[DatabaseSessionBroker, BrokerPrincipal, TestCertificateIssuer]:
    now = datetime.now(UTC)
    principal = BrokerPrincipal(
        issuer=ISSUER,
        subject=SUBJECT,
        tenant_id=TENANT,
        business_unit_id=BUSINESS_UNIT,
        roles=frozenset({"finance_verifier"}),
        jti="one-time-jti-001",
        issued_at=now - timedelta(seconds=10),
        expires_at=now + timedelta(minutes=10),
        authentication_time=now - timedelta(seconds=10),
        acr="urn:customer:loa:2",
        amr=frozenset({"pwd", "mfa"}),
    )
    directory_principal = DatabasePrincipal(
        issuer=ISSUER,
        subject=SUBJECT,
        tenant_id=TENANT,
        business_unit_id=BUSINESS_UNIT,
        database_role="pwr_finance_user_001",
        active=True,
        finance_verifier=True,
    )
    signer = TestCertificateIssuer()
    broker = DatabaseSessionBroker(
        policy=BrokerPolicy(
            issuer=ISSUER,
            audience="powerops-db-session-broker",
            jwks_url="https://idp.customer.example/.well-known/jwks.json",
            allowed_acrs=frozenset({"urn:customer:loa:2"}),
            required_amr=frozenset({"mfa"}),
            certificate_ttl_seconds=120,
        ),
        token_verifier=StaticTokenVerifier(principal),
        directory=StaticDirectory(directory_principal),
        replay_guard=InMemoryReplayGuard(),
        certificate_issuer=signer,
    )
    return broker, principal, signer


def make_csr(common_name: str = "attacker-selected-name") -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    request = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .sign(key, hashes.SHA256())
    )
    return request.public_bytes(serialization.Encoding.PEM).decode("ascii")


def test_broker_issues_short_lived_certificate_for_directory_role() -> None:
    broker, principal, _ = build_fixture()
    now = datetime.now(UTC)
    issued = broker.issue_session(
        token="signed-customer-token",
        csr_pem=make_csr(),
        now=now,
    )

    certificate = x509.load_pem_x509_certificate(issued.certificate_pem.encode("ascii"))
    common_name = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    assert issued.database_role == "pwr_finance_user_001"
    assert len(common_name) == 1
    assert common_name[0].value == "pwr_finance_user_001"
    assert issued.expires_at <= now + timedelta(seconds=120)
    assert issued.expires_at <= principal.expires_at


def test_broker_rejects_replayed_token_identifier() -> None:
    broker, _, _ = build_fixture()
    csr = make_csr()
    broker.issue_session(token="signed-customer-token", csr_pem=csr)
    with pytest.raises(BrokerReplayError):
        broker.issue_session(token="signed-customer-token", csr_pem=csr)


def test_broker_requires_finance_verifier_entitlement() -> None:
    broker, principal, signer = build_fixture()
    unentitled = BrokerPrincipal(
        issuer=principal.issuer,
        subject=principal.subject,
        tenant_id=principal.tenant_id,
        business_unit_id=principal.business_unit_id,
        roles=frozenset({"investigator"}),
        jti="unentitled-jti",
        issued_at=principal.issued_at,
        expires_at=principal.expires_at,
        authentication_time=principal.authentication_time,
        acr=principal.acr,
        amr=principal.amr,
    )
    broker._token_verifier = StaticTokenVerifier(unentitled)  # type: ignore[attr-defined]
    with pytest.raises(BrokerAuthorizationError):
        broker.issue_session(token="signed-customer-token", csr_pem=make_csr())
    assert signer is not None


def test_broker_rejects_inactive_customer_database_identity() -> None:
    broker, _, _ = build_fixture()
    broker._directory = StaticDirectory(None)  # type: ignore[attr-defined]
    with pytest.raises(BrokerAuthorizationError):
        broker.issue_session(token="signed-customer-token", csr_pem=make_csr())


def test_broker_rejects_invalid_csr() -> None:
    broker, _, _ = build_fixture()
    with pytest.raises(BrokerAuthenticationError):
        broker.issue_session(token="signed-customer-token", csr_pem="not a CSR")


def test_broker_does_not_use_csr_subject_as_database_role() -> None:
    broker, _, _ = build_fixture()
    issued = broker.issue_session(
        token="signed-customer-token",
        csr_pem=make_csr("pwr_privileged_admin"),
    )
    certificate = x509.load_pem_x509_certificate(issued.certificate_pem.encode("ascii"))
    common_name = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    assert common_name[0].value == "pwr_finance_user_001"
