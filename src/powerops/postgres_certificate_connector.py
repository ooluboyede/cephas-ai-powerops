"""Customer certificate-authenticated PostgreSQL connector for human sessions.

This connector intentionally opens one physical psycopg connection per human
operation. It never uses the shared BU pool and never accepts a caller-selected
PostgreSQL role or DSN. A trusted credential provider supplies the database role
and certificate paths produced by the customer-operated identity broker.
"""
from __future__ import annotations

import hmac
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID
import re

from powerops.human_session_issuer import HumanSessionCredentialStore
from powerops.human_sessions import HumanSessionPrincipal, HumanSessionRejected


@dataclass(frozen=True, slots=True)
class HumanPostgresCredentials:
    """Short-lived, customer-issued certificate material for one human identity."""

    session_id: UUID
    issuer: str
    subject: str
    tenant_id: UUID
    business_unit_id: UUID
    finance_operator: bool
    finance_verifier: bool
    database_role: str
    host: str
    port: int
    database_name: str
    certificate_path: Path
    private_key_path: Path
    root_certificate_path: Path
    expires_at: datetime


class HumanPostgresCredentialProvider(Protocol):
    """Retrieve credentials minted for this exact verified human principal."""

    def materialize_credentials(
        self, principal: HumanSessionPrincipal
    ) -> AbstractContextManager[HumanPostgresCredentials]:
        """Materialize exact-session credentials only for the connection lifetime."""




class VaultBackedHumanPostgresCredentialProvider:
    """Materialize one customer-vault session into short-lived 0600 files.

    The configured temporary directory must be customer-managed, owner-only,
    and mounted on encrypted ephemeral storage (for example tmpfs). The vault
    adapter is responsible for encryption at rest and access auditing.
    """

    _MAX_CERTIFICATE_TTL = timedelta(seconds=300)

    def __init__(
        self,
        credential_store: HumanSessionCredentialStore,
        *,
        host: str,
        port: int,
        database_name: str,
        root_certificate_path: Path,
        secure_temp_directory: Path,
    ) -> None:
        self._credential_store = credential_store
        self._host = host
        self._port = port
        self._database_name = database_name
        self._root_certificate_path = root_certificate_path
        self._secure_temp_directory = secure_temp_directory

    @contextmanager
    def materialize_credentials(
        self, principal: HumanSessionPrincipal
    ) -> Iterator[HumanPostgresCredentials]:
        try:
            stored = self._credential_store.get_session(principal.session_id)
        except Exception:
            raise HumanSessionRejected(
                "Customer human-session vault lookup failed"
            ) from None
        if stored is None:
            raise HumanSessionRejected("Customer human-session lease is missing or expired")

        now = datetime.now(UTC)
        expiry = stored.expires_at
        if expiry.tzinfo is None:
            raise HumanSessionRejected("Stored session expiry must be timezone-aware")
        expiry = expiry.astimezone(UTC)
        if expiry <= now or expiry > now + self._MAX_CERTIFICATE_TTL:
            raise HumanSessionRejected("Stored human-session lease is expired or too long")
        if (
            stored.session_id != principal.session_id
            or stored.issuer != principal.issuer
            or stored.subject != principal.subject
            or stored.tenant_id != principal.tenant_id
            or stored.business_unit_id != principal.business_unit_id
            or stored.finance_operator != principal.finance_operator
            or stored.finance_verifier != principal.finance_verifier
        ):
            raise HumanSessionRejected(
                "Stored customer credentials do not match the verified human session"
            )


        try:
            certificate = x509.load_pem_x509_certificate(
                stored.certificate_pem.encode("ascii")
            )
            private_key = serialization.load_pem_private_key(
                stored.private_key_pem.encode("ascii"),
                password=None,
            )
            certificate_public_key = certificate.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            private_public_key = private_key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        except (ValueError, TypeError):
            raise HumanSessionRejected(
                "Customer vault returned invalid certificate or private-key material"
            ) from None
        if not hmac.compare_digest(certificate_public_key, private_public_key):
            raise HumanSessionRejected(
                "Customer certificate and private key do not form a matching pair"
            )
        common_names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if not common_names or common_names[0].value != stored.database_role:
            raise HumanSessionRejected(
                "Customer certificate common name does not match its database role"
            )
        certificate_not_before = certificate.not_valid_before_utc
        certificate_not_after = certificate.not_valid_after_utc
        if (
            certificate_not_before > now
            or certificate_not_after <= now
            or certificate_not_after > expiry
        ):
            raise HumanSessionRejected(
                "Customer certificate validity does not match the stored session lease"
            )

        temp_root = self._secure_temp_directory
        try:
            metadata = temp_root.lstat()
        except OSError:
            raise HumanSessionRejected(
                "Customer secure temporary directory is unavailable"
            ) from None
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise HumanSessionRejected("Customer secure temporary path must be a real directory")
        if metadata.st_uid != os.geteuid():
            raise HumanSessionRejected("Customer secure temporary directory has the wrong owner")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise HumanSessionRejected(
                "Customer secure temporary directory permissions are too broad"
            )

        with tempfile.TemporaryDirectory(
            prefix="powerops-human-session-",
            dir=str(temp_root),
        ) as temporary:
            directory = Path(temporary)
            os.chmod(directory, 0o700)
            certificate_path = directory / "client.crt"
            private_key_path = directory / "client.key"
            certificate_path.write_text(stored.certificate_pem, encoding="ascii")
            private_key_path.write_text(stored.private_key_pem, encoding="ascii")
            os.chmod(certificate_path, 0o600)
            os.chmod(private_key_path, 0o600)
            yield HumanPostgresCredentials(
                session_id=stored.session_id,
                issuer=stored.issuer,
                subject=stored.subject,
                tenant_id=stored.tenant_id,
                business_unit_id=stored.business_unit_id,
                finance_operator=stored.finance_operator,
                finance_verifier=stored.finance_verifier,
                database_role=stored.database_role,
                host=self._host,
                port=self._port,
                database_name=self._database_name,
                certificate_path=certificate_path,
                private_key_path=private_key_path,
                root_certificate_path=self._root_certificate_path,
                expires_at=expiry,
            )


class PsycopgConnectFactory(Protocol):
    """Small seam for production psycopg and deterministic connector tests."""

    def __call__(self, **kwargs: Any) -> Any:
        """Open one PostgreSQL connection using the supplied TLS parameters."""


def _default_psycopg_connect(**kwargs: Any) -> Any:
    """Load the optional psycopg dependency only when a human session is opened."""
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(**kwargs, row_factory=dict_row)


class PsycopgHumanSessionConnector:
    """Open a fresh verify-full TLS connection as the broker-assigned human role."""

    _ROLE_PATTERN = re.compile(r"^pwr_[a-z0-9_]{1,40}$")
    _MAX_CERTIFICATE_TTL = timedelta(seconds=300)

    def __init__(
        self,
        credential_provider: HumanPostgresCredentialProvider,
        *,
        connect_factory: PsycopgConnectFactory = _default_psycopg_connect,
        connect_timeout_seconds: int = 5,
    ) -> None:
        if not 1 <= connect_timeout_seconds <= 30:
            raise ValueError("PostgreSQL connect timeout must be between 1 and 30 seconds")
        self._credential_provider = credential_provider
        self._connect_factory = connect_factory
        self._connect_timeout_seconds = connect_timeout_seconds

    @staticmethod
    def _require_file(path: Path, *, private: bool = False) -> str:
        try:
            metadata = path.stat()
        except OSError:
            raise HumanSessionRejected(
                "Required customer certificate file is unavailable"
            ) from None
        if not stat.S_ISREG(metadata.st_mode):
            raise HumanSessionRejected("Customer certificate paths must reference regular files")
        if private and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise HumanSessionRejected("Customer private key permissions are too broad")
        return str(path)

    @contextmanager
    def connect(self, principal: HumanSessionPrincipal) -> Iterator[Any]:
        """Open a non-pooled TLS connection and erase temporary key files on exit."""
        try:
            materialized = self._credential_provider.materialize_credentials(principal)
            with materialized as credentials:
                yield from self._connect_with_credentials(principal, credentials)
        except HumanSessionRejected as exc:
            # Preserve locally generated, already-sanitized policy errors.
            # A translated provider rejection may still carry a sensitive cause
            # or unsuppressed context, which must not cross this boundary.
            if exc.__cause__ is None and (
                exc.__context__ is None or exc.__suppress_context__
            ):
                raise
            raise HumanSessionRejected(
                "Customer human-session credentials are unavailable"
            ) from None
        except Exception:
            # Provider and driver exceptions can contain paths, DSNs, or
            # provider diagnostics. Never expose them at the public boundary.
            raise HumanSessionRejected(
                "Customer human-session credentials are unavailable"
            ) from None

    def _connect_with_credentials(
        self,
        principal: HumanSessionPrincipal,
        credentials: HumanPostgresCredentials,
    ) -> Iterator[Any]:
        now = datetime.now(UTC)
        if (
            credentials.session_id != principal.session_id
            or credentials.issuer != principal.issuer
            or credentials.subject != principal.subject
            or credentials.tenant_id != principal.tenant_id
            or credentials.business_unit_id != principal.business_unit_id
            or credentials.finance_operator != principal.finance_operator
            or credentials.finance_verifier != principal.finance_verifier
        ):
            raise HumanSessionRejected(
                "Customer certificate identity does not match the API principal"
            )
        if not self._ROLE_PATTERN.fullmatch(credentials.database_role):
            raise HumanSessionRejected("Customer directory returned an invalid database role")
        if not credentials.host.strip() or not credentials.database_name.strip():
            raise HumanSessionRejected("Customer PostgreSQL host and database are required")
        if not 1 <= credentials.port <= 65535:
            raise HumanSessionRejected("Customer PostgreSQL port is invalid")
        if credentials.expires_at.tzinfo is None:
            raise HumanSessionRejected("Customer certificate expiry must be timezone-aware")
        expiry = credentials.expires_at.astimezone(UTC)
        if expiry <= now or expiry > now + self._MAX_CERTIFICATE_TTL:
            raise HumanSessionRejected(
                "Customer certificate is expired or exceeds the five-minute limit"
            )

        sslrootcert = self._require_file(credentials.root_certificate_path)
        sslcert = self._require_file(credentials.certificate_path)
        sslkey = self._require_file(credentials.private_key_path, private=True)

        # Role comes only from the trusted credential provider. No DSN, startup
        # options, GUC, SET ROLE or shared connection can override the identity.
        connection = self._connect_factory(
            host=credentials.host,
            port=credentials.port,
            dbname=credentials.database_name,
            user=credentials.database_role,
            sslmode="verify-full",
            sslrootcert=sslrootcert,
            sslcert=sslcert,
            sslkey=sslkey,
            connect_timeout=self._connect_timeout_seconds,
            application_name="cephas-powerops-human-session",
            autocommit=False,
        )
        with cast(AbstractContextManager[Any], connection) as managed_connection:
            # Register this exact physical backend before exposing any SQL
            # capability to the application. The function derives PID and
            # backend_start inside PostgreSQL and serializes against revocation.
            with managed_connection.transaction():
                registration = managed_connection.execute(
                    """
                    SELECT powerops_security.register_human_session_backend(%s)
                        AS registered
                    """,
                    (str(credentials.session_id),),
                ).fetchone()
                if not isinstance(registration, dict) or registration.get("registered") is not True:
                    raise HumanSessionRejected(
                        "Customer PostgreSQL session admission was not confirmed"
                    )
            # The transaction context has committed registration here.
            # Any exception/uncertain commit exits without yielding a connection.
            yield managed_connection
