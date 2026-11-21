"""Explicit customer deployment composition for exact-session revocation."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from powerops.credential_revocation_attestation import (
    CredentialRevocationReceiptVerifier,
)
from powerops.human_session_issuer import HumanSessionCredentialStore
from powerops.postgres_principal_verification import (
    verify_revocation_postgres_principals,
)
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
    expected_provisioner_login: str,
    expected_termination_login: str,
    expected_audit_login: str,
    credential_receipt_verifier: CredentialRevocationReceiptVerifier,
) -> HumanSessionRevocationCoordinator:
    """Verify actual PostgreSQL identities before composing revocation.

    Customer deployment must supply three independently configured factories
    and the expected PostgreSQL login names. Each connection is queried for
    session_user/current_user, role memberships, narrowly scoped function
    EXECUTE grants, and direct access to protected registry/audit tables.
    The encrypted credential store remains customer supplied.
    """
    factories = (
        provisioner_connection_factory,
        termination_connection_factory,
        audit_connection_factory,
    )
    if any(not callable(factory) for factory in factories):
        raise ValueError("All customer revocation connection factories are required")
    if len({id(factory) for factory in factories}) != len(factories):
        raise ValueError("Fence, termination and audit credentials must use separate factories")

    verify_revocation_postgres_principals(
        provisioner_connection_factory=provisioner_connection_factory,
        termination_connection_factory=termination_connection_factory,
        audit_connection_factory=audit_connection_factory,
        expected_provisioner_login=expected_provisioner_login,
        expected_termination_login=expected_termination_login,
        expected_audit_login=expected_audit_login,
    )

    backend_control = PsycopgSessionBackendRevocationControl(
        provisioner_connection_factory=provisioner_connection_factory,
        termination_connection_factory=termination_connection_factory,
    )
    audit = PostgresSessionRevocationAudit(
        connection_factory=audit_connection_factory,
        credential_receipt_verifier=credential_receipt_verifier,
    )
    return HumanSessionRevocationCoordinator(
        credential_store=credential_store,
        backend_control=backend_control,
        audit=audit,
        credential_receipt_verifier=credential_receipt_verifier,
    )
