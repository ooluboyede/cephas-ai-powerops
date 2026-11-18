from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from powerops.human_sessions import HumanSessionPrincipal, HumanSessionRejected
from powerops.postgres_certificate_connector import (
    HumanPostgresCredentials,
    PsycopgHumanSessionConnector,
)

ISSUER = "https://identity.customer.example"
SUBJECT = "finance.user.17"
TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BUSINESS_UNIT = UUID("a1000000-0000-4000-8000-000000000001")


def principal() -> HumanSessionPrincipal:
    return HumanSessionPrincipal(
        issuer=ISSUER,
        subject=SUBJECT,
        tenant_id=TENANT,
        business_unit_id=BUSINESS_UNIT,
        finance_verifier=True,
    )


@dataclass
class FakeProvider:
    credentials: HumanPostgresCredentials

    def get_credentials(self, principal_value: HumanSessionPrincipal) -> HumanPostgresCredentials:
        return self.credentials


class FakeConnection:
    pass


def credentials(tmp_path: Path, **overrides: object) -> HumanPostgresCredentials:
    cert = tmp_path / "human.crt"
    key = tmp_path / "human.key"
    root = tmp_path / "customer-root.crt"
    cert.write_text("test certificate", encoding="utf-8")
    key.write_text("test private key", encoding="utf-8")
    root.write_text("test root", encoding="utf-8")
    key.chmod(0o600)
    values: dict[str, object] = {
        "issuer": ISSUER,
        "subject": SUBJECT,
        "tenant_id": TENANT,
        "business_unit_id": BUSINESS_UNIT,
        "finance_operator": False,
        "finance_verifier": True,
        "database_role": "pwr_finance_user_17",
        "host": "postgres.customer.example",
        "port": 5432,
        "database_name": "powerops",
        "certificate_path": cert,
        "private_key_path": key,
        "root_certificate_path": root,
        "expires_at": datetime.now(UTC) + timedelta(minutes=4),
    }
    values.update(overrides)
    return HumanPostgresCredentials(**values)  # type: ignore[arg-type]


def test_connector_opens_fresh_verify_full_tls_connection(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    connection = FakeConnection()

    def connect_factory(**kwargs: Any) -> FakeConnection:
        captured.update(kwargs)
        return connection

    provider = FakeProvider(credentials(tmp_path))
    connector = PsycopgHumanSessionConnector(provider, connect_factory=connect_factory)

    assert connector.connect(principal()) is connection
    assert captured["user"] == "pwr_finance_user_17"
    assert captured["sslmode"] == "verify-full"
    assert captured["sslcert"].endswith("human.crt")
    assert captured["sslkey"].endswith("human.key")
    assert captured["sslrootcert"].endswith("customer-root.crt")
    assert captured["autocommit"] is False
    assert "dsn" not in captured
    assert "options" not in captured


@pytest.mark.parametrize(
    "overrides",
    [
        {"issuer": "https://other.customer.example"},
        {"subject": "different-user"},
        {"tenant_id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")},
        {"business_unit_id": UUID("b1000000-0000-4000-8000-000000000001")},
        {"database_role": "postgres"},
        {"database_role": "pwr_finance_user; SET ROLE postgres"},
        {"port": 0},
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        {"expires_at": datetime.now(UTC) + timedelta(minutes=6)},
        {"expires_at": datetime.now()},
    ],
)
def test_connector_rejects_untrusted_or_invalid_credentials(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    called = False

    def connect_factory(**kwargs: Any) -> FakeConnection:
        nonlocal called
        called = True
        return FakeConnection()

    connector = PsycopgHumanSessionConnector(
        FakeProvider(credentials(tmp_path, **overrides)),
        connect_factory=connect_factory,
    )
    with pytest.raises(HumanSessionRejected):
        connector.connect(principal())
    assert called is False


def test_connector_rejects_private_key_with_group_or_world_permissions(
    tmp_path: Path,
) -> None:
    value = credentials(tmp_path)
    value.private_key_path.chmod(0o644)
    connector = PsycopgHumanSessionConnector(
        FakeProvider(value),
        connect_factory=lambda **kwargs: FakeConnection(),
    )

    with pytest.raises(HumanSessionRejected, match="permissions"):
        connector.connect(principal())


def test_connector_fails_closed_when_certificate_file_is_missing(tmp_path: Path) -> None:
    value = credentials(tmp_path)
    value.certificate_path.unlink()
    connector = PsycopgHumanSessionConnector(
        FakeProvider(value),
        connect_factory=lambda **kwargs: FakeConnection(),
    )

    with pytest.raises(HumanSessionRejected, match="unavailable"):
        connector.connect(principal())


def test_connector_fails_closed_when_credential_provider_is_unavailable(
    tmp_path: Path,
) -> None:
    class UnavailableProvider:
        def get_credentials(
            self, principal_value: HumanSessionPrincipal
        ) -> HumanPostgresCredentials:
            raise RuntimeError("directory unavailable")

    connector = PsycopgHumanSessionConnector(
        UnavailableProvider(),
        connect_factory=lambda **kwargs: FakeConnection(),
    )

    with pytest.raises(HumanSessionRejected, match="unavailable"):
        connector.connect(principal())
