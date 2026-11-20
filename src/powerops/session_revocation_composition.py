"""Explicit customer deployment composition for exact-session revocation."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from powerops.human_session_issuer import HumanSessionCredentialStore
from powerops.postgres_session_revocation import (
    ConnectionFactory,
    PsycopgSessionBackendRevocationControl,
)
from powerops.postgres_session_revocation_audit import (
    PostgresSessionRevocationAudit,
)
from powerops.session_revocation import HumanSessionRevocationCoordinator


def build_human_session_revocation_coordinator(
    *,
    credential_store: HumanSessionCredentialStore,
    provisioner_connection_factory: ConnectionFactory,
    termination_connection_factory: ConnectionFactory,
    audit_connection_factory: Callable[[], Any],
) -> HumanSessionRevocationCoordinator:
    """Compose revocation using three independent customer trust boundaries.

    The encrypted credential store is supplied by the customer deployment;
    this function deliberately does not invent a vault provider or fall back
    to a shared database credential. PostgreSQL fence, backend termination,
    and audit writes each receive separate connection factories.
    """
    factories = (
        provisioner_connection_factory,
        termination_connection_factory,
        audit_connection_factory,
    )
    if any(not callable(factory) for factory in factories):
        raise ValueError("All customer revocation connection factories are required")
    if len({id(factory) for factory in factories}) != len(factories):
        raise ValueError("Fence, termination and audit credentials must be separate")

    backend_control = PsycopgSessionBackendRevocationControl(
        provisioner_connection_factory=provisioner_connection_factory,
        termination_connection_factory=termination_connection_factory,
    )
    audit = PostgresSessionRevocationAudit(
        connection_factory=audit_connection_factory
    )
    return HumanSessionRevocationCoordinator(
        credential_store=credential_store,
        backend_control=backend_control,
        audit=audit,
    )
