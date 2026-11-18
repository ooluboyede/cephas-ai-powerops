from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from powerops.human_session_issuer import StoredHumanSessionCredential
from powerops.human_sessions import HumanSessionPrincipal, HumanSessionRejected
from powerops.postgres_certificate_connector import (
    HumanPostgresCredentials,
    PsycopgHumanSessionConnector,
    VaultBackedHumanPostgresCredentialProvider,
)

ISSUER = "https://identity.customer.example"
SUBJECT = "finance.user.17"
TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BUSINESS_UNIT = UUID("a1000000-0000-4000-8000-000000000001")


def principal() -> HumanSessionPrincipal:
    return HumanSessionPrincipal(
        session_id=UUID("f0000000-0000-4000-8000-000000000006"),
        issuer=ISSUER,
        subject=SUBJECT,
        tenant_id=TENANT,
        business_unit_id=BUSINESS_UNIT,
        finance_verifier=True,
    )


@dataclass
class FakeProvider:
    credentials: HumanPostgresCredentials

    @contextmanager
    def materialize_credentials(
        self, principal_value: HumanSessionPrincipal
    ) -> Iterator[HumanPostgresCredentials]:
        yield self.credentials


class FakeConnection:
    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def credentials(tmp_path: Path, **overrides: object) -> HumanPostgresCredentials:
    cert = tmp_path / "human.crt"
    key = tmp_path / "human.key"
    root = tmp_path / "customer-root.crt"
    cert.write_text("test certificate", encoding="utf-8")
    key.write_text("test private key", encoding="utf-8")
    root.write_text("test root", encoding="utf-8")
    key.chmod(0o600)
    values: dict[str, object] = {
        "session_id": UUID("f0000000-0000-4000-8000-000000000006"),
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



class FakeCredentialStore:
    def __init__(self, stored: StoredHumanSessionCredential) -> None:
        self.stored = stored

    def get_session(
        self, session_id: UUID
    ) -> StoredHumanSessionCredential | None:
        return self.stored if session_id == self.stored.session_id else None


def stored_credentials(**overrides: object) -> StoredHumanSessionCredential:
    values: dict[str, object] = {
        "session_id": UUID("f0000000-0000-4000-8000-000000000006"),
        "issuer": ISSUER,
        "subject": SUBJECT,
        "tenant_id": TENANT,
        "business_unit_id": BUSINESS_UNIT,
        "finance_operator": False,
        "finance_verifier": True,
        "database_role": "pwr_finance_user_17",
        "certificate_pem": "-----BEGIN CERTIFICATE-----\\nclient-cert\\n",
        "private_key_pem": "-----BEGIN PRIVATE KEY-----\\nprivate-key\\n",
        "expires_at": datetime.now(UTC) + timedelta(minutes=4),
    }
    values.update(overrides)
    return StoredHumanSessionCredential(**values)  # type: ignore[arg-type]


def test_vault_provider_materializes_exact_session_and_erases_key_files(
    tmp_path: Path,
) -> None:
    secure_temp = tmp_path / "secure-tmp"
    secure_temp.mkdir(mode=0o700)
    secure_temp.chmod(0o700)
    root = tmp_path / "customer-root.crt"
    root.write_text("root certificate", encoding="utf-8")
    provider = VaultBackedHumanPostgresCredentialProvider(
        FakeCredentialStore(stored_credentials()),
        host="postgres.customer.example",
        port=5432,
        database_name="powerops",
        root_certificate_path=root,
        secure_temp_directory=secure_temp,
    )

    with provider.materialize_credentials(principal()) as credentials_value:
        temporary_directory = credentials_value.private_key_path.parent
        assert credentials_value.session_id == principal().session_id
        assert credentials_value.private_key_path.exists()
        assert credentials_value.private_key_path.stat().st_mode & 0o777 == 0o600
        assert temporary_directory.stat().st_mode & 0o777 == 0o700

    assert not temporary_directory.exists()


def test_vault_provider_rejects_credentials_for_another_human(
    tmp_path: Path,
) -> None:
    secure_temp = tmp_path / "secure-tmp"
    secure_temp.mkdir(mode=0o700)
    secure_temp.chmod(0o700)
    provider = VaultBackedHumanPostgresCredentialProvider(
        FakeCredentialStore(stored_credentials(subject="different-user")),
        host="postgres.customer.example",
        port=5432,
        database_name="powerops",
        root_certificate_path=tmp_path / "root.crt",
        secure_temp_directory=secure_temp,
    )

    with pytest.raises(HumanSessionRejected, match="do not match"):
        with provider.materialize_credentials(principal()):
            pytest.fail("Mismatched stored session must not materialize")



def test_vault_provider_rejects_another_session_id(
    tmp_path: Path,
) -> None:
    secure_temp = tmp_path / "secure-tmp"
    secure_temp.mkdir(mode=0o700)
    secure_temp.chmod(0o700)
    provider = VaultBackedHumanPostgresCredentialProvider(
        FakeCredentialStore(
            stored_credentials(
                session_id=UUID("f0000000-0000-4000-8000-000000000099")
            )
        ),
        host="postgres.customer.example",
        port=5432,
        database_name="powerops",
        root_certificate_path=tmp_path / "root.crt",
        secure_temp_directory=secure_temp,
    )

    with pytest.raises(HumanSessionRejected, match="do not match"):
        with provider.materialize_credentials(principal()):
            pytest.fail("A different lease must not be materialized")

def test_vault_provider_rejects_world_accessible_temporary_directory(
    tmp_path: Path,
) -> None:
    secure_temp = tmp_path / "insecure-tmp"
    secure_temp.mkdir(mode=0o755)
    secure_temp.chmod(0o755)
    provider = VaultBackedHumanPostgresCredentialProvider(
        FakeCredentialStore(stored_credentials()),
        host="postgres.customer.example",
        port=5432,
        database_name="powerops",
        root_certificate_path=tmp_path / "root.crt",
        secure_temp_directory=secure_temp,
    )

    with pytest.raises(HumanSessionRejected, match="permissions"):
        with provider.materialize_credentials(principal()):
            pytest.fail("Insecure temporary directory must be rejected")

def test_connector_opens_fresh_verify_full_tls_connection(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    connection = FakeConnection()

    def connect_factory(**kwargs: Any) -> FakeConnection:
        captured.update(kwargs)
        return connection

    provider = FakeProvider(credentials(tmp_path))
    connector = PsycopgHumanSessionConnector(provider, connect_factory=connect_factory)

    with connector.connect(principal()) as opened:
        assert opened is connection
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
        {"session_id": UUID("f0000000-0000-4000-8000-000000000099")},
        {"issuer": "https://other.customer.example"},
        {"subject": "different-user"},
        {"tenant_id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")},
        {"business_unit_id": UUID("b1000000-0000-4000-8000-000000000001")},
        {"finance_operator": True},
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
        with connector.connect(principal()):
            pytest.fail("Invalid credentials must not open a database connection")
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
        with connector.connect(principal()):
            pytest.fail("Insecure private key must not open a database connection")


def test_connector_fails_closed_when_certificate_file_is_missing(tmp_path: Path) -> None:
    value = credentials(tmp_path)
    value.certificate_path.unlink()
    connector = PsycopgHumanSessionConnector(
        FakeProvider(value),
        connect_factory=lambda **kwargs: FakeConnection(),
    )

    with pytest.raises(HumanSessionRejected, match="unavailable"):
        with connector.connect(principal()):
            pytest.fail("Missing certificate must not open a database connection")


def test_connector_fails_closed_when_credential_provider_is_unavailable(
    tmp_path: Path,
) -> None:
    class UnavailableProvider:
        @contextmanager
        def materialize_credentials(
            self, principal_value: HumanSessionPrincipal
        ) -> Iterator[HumanPostgresCredentials]:
            raise RuntimeError("directory unavailable")
            yield credentials(tmp_path)

    connector = PsycopgHumanSessionConnector(
        UnavailableProvider(),
        connect_factory=lambda **kwargs: FakeConnection(),
    )

    with pytest.raises(HumanSessionRejected, match="unavailable"):
        with connector.connect(principal()):
            pytest.fail("Unavailable provider must not open a database connection")
