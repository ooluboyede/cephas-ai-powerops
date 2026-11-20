from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

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


class FakeResult:
    def __init__(self, row: object) -> None:
        self._row = row

    def fetchone(self) -> object:
        return self._row


_DEFAULT_REGISTRATION_ROW = object()


class FakeConnection:
    def __init__(self, registration_row: object = _DEFAULT_REGISTRATION_ROW) -> None:
        self.registration_row = (
            {"registered": True}
            if registration_row is _DEFAULT_REGISTRATION_ROW
            else registration_row
        )
        self.events: list[str] = []
        self.closed = False

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        self.closed = True
        self.events.append("close")
        return None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.events.append("begin")
        try:
            yield
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")

    def execute(self, query: str, params: tuple[str]) -> FakeResult:
        self.events.append("register")
        assert "register_human_session_backend" in query
        assert params == (str(principal().session_id),)
        return FakeResult(self.registration_row)


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
    now = datetime.now(UTC)
    private_key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "pwr_finance_user_17")]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before((now - timedelta(minutes=1)).replace(tzinfo=None))
        .not_valid_after((now + timedelta(minutes=2)).replace(tzinfo=None))
        .sign(private_key, hashes.SHA256())
    )
    certificate_pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
    private_key_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    values: dict[str, object] = {
        "session_id": UUID("f0000000-0000-4000-8000-000000000006"),
        "issuer": ISSUER,
        "subject": SUBJECT,
        "tenant_id": TENANT,
        "business_unit_id": BUSINESS_UNIT,
        "finance_operator": False,
        "finance_verifier": True,
        "database_role": "pwr_finance_user_17",
        "certificate_pem": certificate_pem,
        "private_key_pem": private_key_pem,
        "expires_at": now + timedelta(minutes=3),
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

    with pytest.raises(HumanSessionRejected, match="missing or expired"):
        with provider.materialize_credentials(principal()):
            pytest.fail("A different lease must not be materialized")


def test_vault_provider_rejects_mismatched_certificate_and_private_key(
    tmp_path: Path,
) -> None:
    secure_temp = tmp_path / "secure-tmp"
    secure_temp.mkdir(mode=0o700)
    secure_temp.chmod(0o700)
    wrong_key = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    provider = VaultBackedHumanPostgresCredentialProvider(
        FakeCredentialStore(stored_credentials(private_key_pem=wrong_key)),
        host="postgres.customer.example",
        port=5432,
        database_name="powerops",
        root_certificate_path=tmp_path / "root.crt",
        secure_temp_directory=secure_temp,
    )

    with pytest.raises(HumanSessionRejected, match="matching pair"):
        with provider.materialize_credentials(principal()):
            pytest.fail("Mismatched certificate/key pair must not be materialized")


def test_vault_provider_rejects_certificate_for_another_database_role(
    tmp_path: Path,
) -> None:
    secure_temp = tmp_path / "secure-tmp"
    secure_temp.mkdir(mode=0o700)
    secure_temp.chmod(0o700)
    provider = VaultBackedHumanPostgresCredentialProvider(
        FakeCredentialStore(stored_credentials(database_role="pwr_another_role")),
        host="postgres.customer.example",
        port=5432,
        database_name="powerops",
        root_certificate_path=tmp_path / "root.crt",
        secure_temp_directory=secure_temp,
    )

    with pytest.raises(HumanSessionRejected, match="common name"):
        with provider.materialize_credentials(principal()):
            pytest.fail("Certificate CN must match the directory-assigned DB role")

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
    assert connection.events == ["begin", "register", "commit", "close"]


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



@pytest.mark.parametrize("registration_row", [None, {}, {"registered": False}, {"registered": 1}])
def test_connector_fails_closed_when_backend_registration_is_not_confirmed(
    tmp_path: Path, registration_row: object
) -> None:
    connection = FakeConnection(registration_row)
    connector = PsycopgHumanSessionConnector(
        FakeProvider(credentials(tmp_path)),
        connect_factory=lambda **kwargs: connection,
    )

    with pytest.raises(HumanSessionRejected, match="admission"):
        with connector.connect(principal()):
            pytest.fail("Unconfirmed backend registration must not yield SQL access")

    assert connection.closed is True
    assert connection.events == ["begin", "register", "rollback", "close"]


def test_connector_closes_without_yielding_when_registration_commit_fails(
    tmp_path: Path,
) -> None:
    class CommitFailureConnection(FakeConnection):
        @contextmanager
        def transaction(self) -> Iterator[None]:
            self.events.append("begin")
            yield
            self.events.append("commit_attempt")
            raise RuntimeError("synthetic uncertain commit outcome")

    connection = CommitFailureConnection()
    connector = PsycopgHumanSessionConnector(
        FakeProvider(credentials(tmp_path)),
        connect_factory=lambda **kwargs: connection,
    )

    with pytest.raises(HumanSessionRejected, match="unavailable"):
        with connector.connect(principal()):
            pytest.fail("A connection with uncertain registration commit must not be yielded")

    assert connection.closed is True
    assert connection.events == ["begin", "register", "commit_attempt", "close"]
