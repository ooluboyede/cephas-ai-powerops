from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import pytest

from powerops.human_sessions import (
    HumanDatabaseSession,
    HumanSessionPrincipal,
    HumanSessionRejected,
)

ISSUER = "https://identity.customer.example"
SUBJECT = "finance.user.17"
TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BUSINESS_UNIT = UUID("a1000000-0000-4000-8000-000000000001")


class FakeConnection:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.commits = 0
        self.rollbacks = 0
        self.application_queries = 0

    def execute(self, query: str) -> FakeConnection:
        assert "resolve_authenticated_human_actor" in query
        return self

    def fetchone(self) -> dict[str, object]:
        return self.row

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
        except Exception:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1


class FakeConnector:
    def __init__(self, row: dict[str, object]) -> None:
        self.connection_value = FakeConnection(row)
        self.closed = False
        self.principal: HumanSessionPrincipal | None = None

    @contextmanager
    def connect(self, principal: HumanSessionPrincipal) -> Iterator[Any]:
        self.principal = principal
        try:
            yield self.connection_value
        finally:
            self.closed = True


def principal(*, finance_verifier: bool = True) -> HumanSessionPrincipal:
    return HumanSessionPrincipal(
        session_id=UUID("f0000000-0000-4000-8000-000000000006"),
        issuer=ISSUER,
        subject=SUBJECT,
        tenant_id=TENANT,
        business_unit_id=BUSINESS_UNIT,
        finance_verifier=finance_verifier,
    )


def actor_row(**overrides: object) -> dict[str, object]:
    return {
        "role_unchanged": True,
        "tenant_id": TENANT,
        "business_unit_id": BUSINESS_UNIT,
        "actor_subject": f"{ISSUER}|{SUBJECT}",
        "finance_operator": False,
        "finance_verifier": True,
        **overrides,
    }


def test_verified_human_session_yields_only_after_database_identity_check() -> None:
    connector = FakeConnector(actor_row())
    session = HumanDatabaseSession(connector)

    with session.connection(principal()) as connection:
        assert connection is connector.connection_value
        assert connector.closed is False

    assert connector.closed is True
    assert connector.connection_value.commits == 1
    assert connector.connection_value.rollbacks == 0
    assert connector.principal == principal()


@pytest.mark.parametrize(
    "overrides",
    [
        {"role_unchanged": False},
        {"tenant_id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")},
        {"business_unit_id": UUID("b1000000-0000-4000-8000-000000000001")},
        {"actor_subject": "https://identity.customer.example|different-user"},
        {"finance_operator": True},
        {"finance_verifier": False},
    ],
)
def test_mismatched_database_identity_fails_before_application_sql(
    overrides: dict[str, object],
) -> None:
    connector = FakeConnector(actor_row(**overrides))
    session = HumanDatabaseSession(connector)

    with pytest.raises(HumanSessionRejected):
        with session.connection(principal()):
            pytest.fail("Application SQL must not run for a mismatched identity")

    assert connector.closed is True
    assert connector.connection_value.commits == 0
    assert connector.connection_value.rollbacks == 1


def test_missing_database_actor_mapping_fails_closed() -> None:
    connector = FakeConnector({})
    session = HumanDatabaseSession(connector)

    with pytest.raises(HumanSessionRejected):
        with session.connection(principal()):
            pytest.fail("An absent mapping must never yield a connection")

    assert connector.connection_value.rollbacks == 1


def test_principal_requires_https_issuer_and_subject() -> None:
    with pytest.raises(ValueError):
        HumanSessionPrincipal(
            session_id=UUID("f0000000-0000-4000-8000-000000000006"),
            issuer="http://identity.customer.example",
            subject=SUBJECT,
            tenant_id=TENANT,
            business_unit_id=BUSINESS_UNIT,
        )
    with pytest.raises(ValueError):
        HumanSessionPrincipal(
            session_id=UUID("f0000000-0000-4000-8000-000000000006"),
            issuer=ISSUER,
            subject=" ",
            tenant_id=TENANT,
            business_unit_id=BUSINESS_UNIT,
        )
