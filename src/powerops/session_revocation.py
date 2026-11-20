"""Fail-closed orchestration for exact human-session revocation.

The PostgreSQL control-plane adapter is customer supplied. It must implement
an atomic admission fence keyed by the exact session UUID, derive backend
identifiers from trusted database state (never caller input), terminate only
those backends, and verify their disappearance before returning.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from powerops.auth import AuthenticatedPrincipal
from powerops.credential_revocation_attestation import (
    CredentialRevocationReceipt,
    CredentialRevocationReceiptVerifier,
)
from powerops.human_session_issuer import HumanSessionCredentialStore


REVOCATION_ROLE = "powerops_session_revoker"
GLOBAL_REVOCATION_ROLE = "powerops_global_session_revoker"


class SessionRevocationError(RuntimeError):
    """Revocation did not reach a verified terminal state."""


@dataclass(frozen=True, slots=True)
class SessionRevocationResult:
    session_id: UUID
    terminated_backend_count: int
    verified: bool


class SessionBackendRevocationControl(Protocol):
    """Customer PostgreSQL control-plane contract for one exact session.

    Implementations MUST:
    - use a trusted, separately privileged control connection;
    - atomically fence new admissions for this exact session UUID;
    - resolve backend PIDs from trusted DB state bound to that UUID;
    - never accept caller-supplied PIDs or terminate by role/tenant alone;
    - terminate only those exact backends and verify they have disappeared;
    - make every operation idempotent and safe to retry after partial failure;
    - use bounded lock/statement timeouts and fail closed on uncertainty.
    """

    def fence_session(self, session_id: UUID) -> None:
        """Atomically prevent new database admissions for this exact session."""

    def terminate_session_backends(self, session_id: UUID) -> int:
        """Terminate trusted, exact-session backend mappings; return count."""

    def active_session_backend_count(self, session_id: UUID) -> int:
        """Return the verified count of remaining exact-session backends."""


class SessionRevocationAudit(Protocol):
    """Secret-free customer audit sink."""

    def record_event(
        self,
        *,
        event_type: str,
        actor_subject: str,
        session_id: UUID,
        outcome: str,
        terminated_backend_count: int,
        credential_revoked: bool,
        admission_fenced: bool,
        backend_termination_verified: bool,
        credential_receipt: CredentialRevocationReceipt | None,
    ) -> None:
        """Persist immutable status and optional signed receipt evidence."""


class HumanSessionRevocationCoordinator:
    """Fence, revoke, terminate and verify one human database session."""

    def __init__(
        self,
        *,
        credential_store: HumanSessionCredentialStore,
        backend_control: SessionBackendRevocationControl,
        audit: SessionRevocationAudit,
        credential_receipt_verifier: CredentialRevocationReceiptVerifier,
    ) -> None:
        self._credential_store = credential_store
        self._backend_control = backend_control
        self._audit = audit
        self._credential_receipt_verifier = credential_receipt_verifier

    def revoke(
        self, *, actor: AuthenticatedPrincipal, session_id: UUID
    ) -> SessionRevocationResult:
        """Revoke one exact session; never report success without verification."""
        if not isinstance(session_id, UUID):
            raise SessionRevocationError("A valid exact session UUID is required")

        # Resolve scope through a metadata-only credential-store operation. Do
        # not materialize certificates/private keys merely to authorize access.
        try:
            target_scope = self._credential_store.get_session_scope(session_id)
        except Exception:
            raise SessionRevocationError(
                "Target human-session authorization could not be verified"
            ) from None
        if (
            not isinstance(target_scope, tuple)
            or len(target_scope) != 2
            or not all(isinstance(value, UUID) for value in target_scope)
        ):
            raise SessionRevocationError(
                "Target human-session authorization could not be verified"
            )

        is_global_revoker = GLOBAL_REVOCATION_ROLE in actor.roles
        is_scoped_revoker = (
            REVOCATION_ROLE in actor.roles
            and actor.tenant_id == target_scope[0]
            and actor.business_unit_id == target_scope[1]
        )
        if not (is_global_revoker or is_scoped_revoker):
            raise SessionRevocationError(
                "Actor is not authorized to revoke this tenant/business-unit session"
            )

        terminated = 0
        store_revoked = False
        credential_receipt = None
        fenced = False
        verified = False

        # Attempt both independent containment controls even if one fails.
        # This minimizes the exposure window during a partial outage.
        try:
            receipt = self._credential_store.revoke_session(session_id)
            if isinstance(receipt, CredentialRevocationReceipt):
                credential_receipt = receipt
            store_revoked = self._credential_receipt_verifier.verify(
                receipt, session_id=session_id
            )
        except Exception:
            store_revoked = False

        try:
            self._backend_control.fence_session(session_id)
            fenced = True
        except Exception:
            pass

        if fenced:
            try:
                terminated = self._backend_control.terminate_session_backends(session_id)
                remaining = self._backend_control.active_session_backend_count(session_id)
                verified = (
                    isinstance(terminated, int)
                    and not isinstance(terminated, bool)
                    and terminated >= 0
                    and isinstance(remaining, int)
                    and not isinstance(remaining, bool)
                    and remaining == 0
                )
            except Exception:
                verified = False

        if store_revoked and fenced and verified:
            try:
                self._audit.record_event(
                    event_type="human_database_session_revoked",
                    actor_subject=actor.subject,
                    session_id=session_id,
                    outcome="verified",
                    terminated_backend_count=terminated,
                    credential_revoked=store_revoked,
                    admission_fenced=fenced,
                    backend_termination_verified=verified,
                    credential_receipt=credential_receipt,
                )
            except Exception:
                self._record_failure(
                    actor, session_id, terminated, store_revoked, fenced, verified,
                    credential_receipt,
                )
                raise SessionRevocationError(
                    "Revocation containment completed, but its audit record could not "
                    "be confirmed; operation remains incomplete"
                ) from None
            return SessionRevocationResult(
                session_id=session_id,
                terminated_backend_count=terminated,
                verified=True,
            )

        self._record_failure(
            actor, session_id, terminated, store_revoked, fenced, verified,
            credential_receipt,
        )
        raise SessionRevocationError(
            "Human database session revocation is incomplete; retry and verify"
        ) from None

    def _record_failure(
        self,
        actor: AuthenticatedPrincipal,
        session_id: UUID,
        terminated: int,
        store_revoked: bool,
        fenced: bool,
        verified: bool,
        credential_receipt: CredentialRevocationReceipt | None,
    ) -> None:
        # Do not serialize provider exceptions, credentials, or backend details.
        try:
            self._audit.record_event(
                event_type="human_database_session_revocation_attempt",
                actor_subject=actor.subject,
                session_id=session_id,
                outcome="incomplete",
                terminated_backend_count=terminated,
                credential_revoked=store_revoked,
                admission_fenced=fenced,
                backend_termination_verified=verified,
                credential_receipt=credential_receipt,
            )
        except Exception:
            # Audit unavailability must not turn a partial revocation into success.
            pass
