"""Per-human PostgreSQL session boundary for Revenue Assurance.

The connector is customer-owned and must authenticate with the short-lived
client certificate issued for this principal. This boundary deliberately uses
one connection per operation: it does not reuse the shared BU service pool or
multiplex connections between human identities.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


class HumanSessionRejected(RuntimeError):
    """The database session does not prove the expected human identity."""


@dataclass(frozen=True, slots=True)
class HumanSessionPrincipal:
    """Verified API identity; never populated from request-supplied scope."""

    issuer: str
    subject: str
    tenant_id: UUID
    business_unit_id: UUID
    finance_verifier: bool = False

    def __post_init__(self) -> None:
        if not self.issuer.startswith("https://") or not self.subject.strip():
            raise ValueError("A verified HTTPS issuer and non-empty subject are required")


class HumanSessionConnector(Protocol):
    """Customer adapter that opens a fresh cert-authenticated connection.

    Implementations must use the broker-issued certificate/private key, verify
    the PostgreSQL server certificate, and must not return a shared pooled
    connection. The database role is selected by the customer directory, never
    by this caller.
    """

    def connect(self, principal: HumanSessionPrincipal) -> AbstractContextManager[Any]:
        """Open and close one database connection for this human principal."""


class HumanDatabaseSession:
    """Verify the PostgreSQL-authenticated human before yielding any SQL access."""

    _IDENTITY_QUERY = """
        SELECT (session_user = current_user) AS role_unchanged,
               actor.tenant_id,
               actor.business_unit_id,
               actor.actor_subject,
               actor.finance_verifier
        FROM powerops_security.resolve_authenticated_human_actor() AS actor
    """

    def __init__(self, connector: HumanSessionConnector) -> None:
        self._connector = connector

    @contextmanager
    def connection(
        self, principal: HumanSessionPrincipal
    ) -> Iterator[Any]:
        """Open a non-pooled session and fail closed before application SQL."""
        with self._connector.connect(principal) as connection:
            with connection.transaction():
                row = connection.execute(self._IDENTITY_QUERY).fetchone()
                expected_subject = f"{principal.issuer}|{principal.subject}"
                if (
                    not isinstance(row, dict)
                    or row.get("role_unchanged") is not True
                    or row.get("tenant_id") != principal.tenant_id
                    or row.get("business_unit_id") != principal.business_unit_id
                    or row.get("actor_subject") != expected_subject
                    or row.get("finance_verifier") is not principal.finance_verifier
                ):
                    raise HumanSessionRejected(
                        "PostgreSQL session identity does not match the verified human"
                    )
                yield connection
