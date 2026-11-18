from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from powerops.auth import AuthenticatedPrincipal
from powerops.identity_broker import (
    BrokerAuthorizationError,
    BrokerDependencyUnavailable,
    IssuedDatabaseSession,
)
from powerops.human_session_issuer import HumanSessionIssuer

ISSUER = "https://identity.customer.example"
SUBJECT = "finance.user.17"
TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BUSINESS_UNIT = UUID("a1000000-0000-4000-8000-000000000001")


def principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject=SUBJECT,
        tenant_id=TENANT,
        business_unit_id=BUSINESS_UNIT,
        roles=frozenset({"finance_verifier"}),
        issuer=ISSUER,
    )


@dataclass
class FakeBroker:
    issued: IssuedDatabaseSession
    csr_pem: str = ""

    def issue_session(self, *, token: str, csr_pem: str) -> IssuedDatabaseSession:
        assert token == "fresh-step-up-token"
        self.csr_pem = csr_pem
        return self.issued


class FakeCredentialStore:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def store_session(self, **values: object) -> None:
        self.values.update(values)


def issued_session(**overrides: object) -> IssuedDatabaseSession:
    values: dict[str, object] = {
        "certificate_pem": "-----BEGIN CERTIFICATE-----\ncustomer-signed\n",
        "expires_at": datetime.now(UTC) + timedelta(minutes=2),
        "database_role": "pwr_finance_user_17",
        "session_id": uuid4(),
        "issuer": ISSUER,
        "subject": SUBJECT,
        "tenant_id": TENANT,
        "business_unit_id": BUSINESS_UNIT,
        "finance_operator": False,
        "finance_verifier": True,
    }
    values.update(overrides)
    return IssuedDatabaseSession(**values)  # type: ignore[arg-type]


def test_session_issuer_keeps_private_key_server_side_and_returns_only_lease() -> None:
    broker = FakeBroker(issued_session())
    store = FakeCredentialStore()
    issuer = HumanSessionIssuer(broker=broker, credential_store=store)

    lease = issuer.create_session(principal=principal(), broker_token="fresh-step-up-token")

    assert broker.csr_pem.startswith("-----BEGIN CERTIFICATE REQUEST-----")
    assert store.values["certificate_pem"] == broker.issued.certificate_pem
    private_key = str(store.values["private_key_pem"])
    assert private_key.startswith("-----BEGIN PRIVATE KEY-----")
    assert lease.session_id == broker.issued.session_id
    assert lease.database_role == "pwr_finance_user_17"
    assert not hasattr(lease, "certificate_pem")
    assert not hasattr(lease, "private_key_pem")


@pytest.mark.parametrize(
    "overrides",
    [
        {"issuer": "https://other.customer.example"},
        {"subject": "different-user"},
        {"tenant_id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")},
        {"business_unit_id": UUID("b1000000-0000-4000-8000-000000000001")},
        {"finance_verifier": False},
        {"database_role": "postgres"},
    ],
)
def test_session_issuer_rejects_broker_identity_mismatch(
    overrides: dict[str, object],
) -> None:
    broker = FakeBroker(issued_session(**overrides))
    store = FakeCredentialStore()
    issuer = HumanSessionIssuer(broker=broker, credential_store=store)

    with pytest.raises(BrokerAuthorizationError):
        issuer.create_session(principal=principal(), broker_token="fresh-step-up-token")
    assert store.values == {}


def test_session_issuer_fails_closed_if_customer_store_is_unavailable() -> None:
    class UnavailableStore:
        def store_session(self, **values: object) -> None:
            raise RuntimeError("vault unavailable")

    issuer = HumanSessionIssuer(
        broker=FakeBroker(issued_session()),
        credential_store=UnavailableStore(),
    )
    with pytest.raises(BrokerDependencyUnavailable):
        issuer.create_session(principal=principal(), broker_token="fresh-step-up-token")



def test_session_issuer_accepts_finance_operator_without_verifier_entitlement() -> None:
    operator = AuthenticatedPrincipal(
        subject=SUBJECT,
        tenant_id=TENANT,
        business_unit_id=BUSINESS_UNIT,
        roles=frozenset({"finance_operator"}),
        issuer=ISSUER,
    )
    broker = FakeBroker(issued_session(finance_operator=True, finance_verifier=False))
    store = FakeCredentialStore()
    issuer = HumanSessionIssuer(broker=broker, credential_store=store)

    lease = issuer.create_session(principal=operator, broker_token="fresh-step-up-token")

    assert lease.database_role == "pwr_finance_user_17"
    assert store.values["finance_operator"] is True
    assert store.values["finance_verifier"] is False


def test_session_issuer_rejects_principal_with_both_finance_roles() -> None:
    dual_role = AuthenticatedPrincipal(
        subject=SUBJECT,
        tenant_id=TENANT,
        business_unit_id=BUSINESS_UNIT,
        roles=frozenset({"finance_operator", "finance_verifier"}),
        issuer=ISSUER,
    )
    issuer = HumanSessionIssuer(
        broker=FakeBroker(issued_session()),
        credential_store=FakeCredentialStore(),
    )

    with pytest.raises(BrokerAuthorizationError):
        issuer.create_session(principal=dual_role, broker_token="fresh-step-up-token")

def test_session_issuer_rejects_non_finance_api_principal() -> None:
    broker = FakeBroker(issued_session())
    store = FakeCredentialStore()
    issuer = HumanSessionIssuer(broker=broker, credential_store=store)
    unentitled = AuthenticatedPrincipal(
        subject=SUBJECT,
        tenant_id=TENANT,
        business_unit_id=BUSINESS_UNIT,
        roles=frozenset({"revenue_analyst"}),
        issuer=ISSUER,
    )

    with pytest.raises(BrokerAuthorizationError):
        issuer.create_session(principal=unentitled, broker_token="fresh-step-up-token")
    assert broker.csr_pem == ""
