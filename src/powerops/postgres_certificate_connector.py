"""Customer certificate-authenticated PostgreSQL connector for human sessions.

This connector intentionally opens one physical psycopg connection per human
operation. It never uses the shared BU pool and never accepts a caller-selected
PostgreSQL role or DSN. A trusted credential provider supplies the database role
and certificate paths produced by the customer-operated identity broker.
"""
from __future__ import annotations

import stat
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID
import re

from powerops.human_sessions import HumanSessionPrincipal, HumanSessionRejected


@dataclass(frozen=True, slots=True)
class HumanPostgresCredentials:
    """Short-lived, customer-issued certificate material for one human identity."""

    issuer: str
    subject: str
    tenant_id: UUID
    business_unit_id: UUID
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

    def get_credentials(
        self, principal: HumanSessionPrincipal
    ) -> HumanPostgresCredentials:
        """Return certificate paths and the directory-assigned database role."""


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
        except OSError as exc:
            raise HumanSessionRejected("Required customer certificate file is unavailable") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise HumanSessionRejected("Customer certificate paths must reference regular files")
        if private and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise HumanSessionRejected("Customer private key permissions are too broad")
        return str(path)

    def connect(self, principal: HumanSessionPrincipal) -> AbstractContextManager[Any]:
        """Open a non-pooled TLS connection; callers must close it via its context."""
        try:
            credentials = self._credential_provider.get_credentials(principal)
        except Exception as exc:
            raise HumanSessionRejected("Customer human-session credentials are unavailable") from exc

        now = datetime.now(UTC)
        if (
            credentials.issuer != principal.issuer
            or credentials.subject != principal.subject
            or credentials.tenant_id != principal.tenant_id
            or credentials.business_unit_id != principal.business_unit_id
        ):
            raise HumanSessionRejected("Customer certificate identity does not match the API principal")
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
            raise HumanSessionRejected("Customer certificate is expired or exceeds the five-minute limit")

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
        return cast(AbstractContextManager[Any], connection)
