from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.types import PublicKeyTypes
from cryptography.x509.oid import NameOID

import jwt

import powerops.identity_broker as identity_broker
from powerops.identity_broker import (
    BrokerAuthenticationError,
    BrokerAuthorizationError,
    BrokerPolicy,
    BrokerPrincipal,
    BrokerReplayError,
    DatabasePrincipal,
    DatabaseSessionBroker,
    OidcBrokerTokenVerifier,
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


class InMemorySessionProvisioner:
    def __init__(self) -> None:
        self.provisioned: dict[UUID, str] = {}
        self.retired: list[UUID] = []

    def provision_session(self, *, session_id: UUID, role_name: str, issuer: str,
                          subject: str, tenant_id: UUID, business_unit_id: UUID,
                          expires_at: datetime) -> int:
        assert role_name.startswith("pwr_")
        assert session_id not in self.provisioned
        self.provisioned[session_id] = role_name
        return len(self.provisioned) + 1000

    def retire_session(self, *, session_id: UUID, reason: str) -> None:
        self.retired.append(session_id)
        self.provisioned.pop(session_id, None)


class InMemoryReplayGuard:
    """Test-only atomicity model; production must use a shared durable store."""

    def __init__(self) -> None:
        self.used: set[str] = set()

    def consume(self, jti: str, csr_fingerprint: str, expires_at: datetime) -> bool:
        if jti in self.used:
            return False
        self.used.add(jti)
        return True


class DisposableCertificateIssuer:
    """Disposable test CA; never use this implementation in customer deployments."""

    def __init__(self) -> None:
        self.ca_key = ec.generate_private_key(ec.SECP256R1())
        self.ca = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-only-ca")]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-only-ca")]))
            .public_key(self.ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before((datetime.now(UTC) - timedelta(seconds=5)).replace(tzinfo=None))
            .not_valid_after((datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None))
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
        public_key: PublicKeyTypes,
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
            .not_valid_before((datetime.now(UTC) - timedelta(seconds=1)).replace(tzinfo=None))
            .not_valid_after(expires_at.replace(tzinfo=None))
            .sign(self.ca_key, hashes.SHA256())
        )
        return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")

    def verify_issued_certificate(
        self,
        certificate_pem: str,
        *,
        database_role: str,
        public_key: PublicKeyTypes,
        expires_at: datetime,
        now: datetime,
    ) -> bool:
        certificate = x509.load_pem_x509_certificate(certificate_pem.encode("ascii"))
        try:
            self.ca.public_key().verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                ec.ECDSA(certificate.signature_hash_algorithm),
            )
        except Exception:
            return False
        issued_key = certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        expected_key = public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return (
            issued_key == expected_key
            and len(names) == 1
            and names[0].value == database_role
            and certificate.not_valid_after_utc <= expires_at
            and certificate.not_valid_after_utc > now
        )


def build_fixture() -> tuple[DatabaseSessionBroker, BrokerPrincipal, DisposableCertificateIssuer]:
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
        finance_operator=False,
        finance_verifier=True,
    )
    signer = DisposableCertificateIssuer()
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
        session_provisioner=InMemorySessionProvisioner(),
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
    assert issued.database_role.startswith("pwr_")
    assert issued.database_role != "pwr_finance_user_001"
    assert issued.issuer == principal.issuer
    assert issued.subject == principal.subject
    assert issued.tenant_id == principal.tenant_id
    assert issued.business_unit_id == principal.business_unit_id
    assert issued.finance_operator is False
    assert issued.finance_verifier is True
    assert len(common_name) == 1
    assert common_name[0].value == issued.database_role
    assert issued.expires_at <= now + timedelta(seconds=120)
    assert issued.expires_at <= principal.expires_at



def test_broker_issues_separate_finance_operator_session() -> None:
    broker, principal, _ = build_fixture()
    operator_principal = BrokerPrincipal(
        issuer=principal.issuer,
        subject=principal.subject,
        tenant_id=principal.tenant_id,
        business_unit_id=principal.business_unit_id,
        roles=frozenset({"finance_operator"}),
        jti="finance-operator-jti-0144",
        issued_at=principal.issued_at,
        expires_at=principal.expires_at,
        authentication_time=principal.authentication_time,
        acr=principal.acr,
        amr=principal.amr,
    )
    broker._token_verifier = StaticTokenVerifier(operator_principal)  # type: ignore[attr-defined]
    broker._directory = StaticDirectory(
        DatabasePrincipal(
            issuer=ISSUER,
            subject=SUBJECT,
            tenant_id=TENANT,
            business_unit_id=BUSINESS_UNIT,
            database_role="pwr_finance_operator_001",
            active=True,
            finance_operator=True,
            finance_verifier=False,
        )
    )  # type: ignore[attr-defined]

    issued = broker.issue_session(
        token="signed-customer-token",
        csr_pem=make_csr(),
    )

    assert issued.database_role.startswith("pwr_")
    assert issued.database_role != "pwr_finance_operator_001"
    assert issued.finance_operator is True
    assert issued.finance_verifier is False


def test_broker_rejects_dual_finance_role_claims() -> None:
    broker, principal, _ = build_fixture()
    dual_role_principal = BrokerPrincipal(
        issuer=principal.issuer,
        subject=principal.subject,
        tenant_id=principal.tenant_id,
        business_unit_id=principal.business_unit_id,
        roles=frozenset({"finance_operator", "finance_verifier"}),
        jti="finance-dual-jti-0144",
        issued_at=principal.issued_at,
        expires_at=principal.expires_at,
        authentication_time=principal.authentication_time,
        acr=principal.acr,
        amr=principal.amr,
    )
    broker._token_verifier = StaticTokenVerifier(dual_role_principal)  # type: ignore[attr-defined]

    with pytest.raises(BrokerAuthorizationError):
        broker.issue_session(token="signed-customer-token", csr_pem=make_csr())

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


def test_oidc_broker_verifier_checks_signature_issuer_audience_and_step_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    now = datetime.now(UTC)
    policy = BrokerPolicy(
        issuer=ISSUER,
        audience="powerops-db-session-broker",
        jwks_url="https://idp.customer.example/.well-known/jwks.json",
        allowed_acrs=frozenset({"urn:customer:loa:2"}),
        required_amr=frozenset({"mfa"}),
    )

    class SigningKey:
        def __init__(self, key: object) -> None:
            self.key = key

    class FakeJwksClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def get_signing_key_from_jwt(self, token: str) -> SigningKey:
            return SigningKey(public_key)

    monkeypatch.setattr(identity_broker, "PyJWKClient", FakeJwksClient)
    verifier = OidcBrokerTokenVerifier(policy)
    claims = {
        "iss": ISSUER,
        "aud": "powerops-db-session-broker",
        "sub": SUBJECT,
        "tenant_id": str(TENANT),
        "business_unit_id": str(BUSINESS_UNIT),
        "roles": ["finance_verifier"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=4)).timestamp()),
        "auth_time": int(now.timestamp()),
        "acr": "urn:customer:loa:2",
        "amr": ["pwd", "mfa"],
        "jti": "cryptographically-signed-one-time-id",
    }
    token = jwt.encode(claims, private_pem, algorithm="RS256")
    verified = verifier.verify(token, now=now)
    assert verified.subject == SUBJECT
    assert verified.tenant_id == TENANT
    assert verified.business_unit_id == BUSINESS_UNIT
    assert "finance_verifier" in verified.roles

    wrong_audience = jwt.encode(
        {**claims, "aud": "powerops-api"}, private_pem, algorithm="RS256"
    )
    with pytest.raises(BrokerAuthenticationError):
        verifier.verify(wrong_audience, now=now)

    insufficient_step_up = jwt.encode(
        {**claims, "amr": ["pwd"], "jti": "different-jti"},
        private_pem,
        algorithm="RS256",
    )
    with pytest.raises(BrokerAuthenticationError):
        verifier.verify(insufficient_step_up, now=now)
