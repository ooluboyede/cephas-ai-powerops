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
from powerops.human_session_issuer import HumanSessionCredentialStore


REVOCATION_ROLE = "powerops_session_revoker"


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
    ) -> None:
        """Persist an immutable audit event without credential or token fields."""


class HumanSessionRevocationCoordinator:
    """Fence, revoke, terminate and verify one human database session."""

    def __init__(
        self,
        *,
        credential_store: HumanSessionCredentialStore,
        backend_control: SessionBackendRevocationControl,
        audit: SessionRevocationAudit,
    ) -> None:
        self._credential_store = credential_store
        self._backend_control = backend_control
        self._audit = audit

    def revoke(
        self, *, actor: AuthenticatedPrincipal, session_id: UUID
    ) -> SessionRevocationResult:
        """Revoke one exact session; never report success without verification."""
        if REVOCATION_ROLE not in actor.roles:
            raise SessionRevocationError("Actor is not authorized to revoke human sessions")
        if not isinstance(session_id, UUID):
            raise SessionRevocationError("A valid exact session UUID is required")

        terminated = 0
        store_revoked = False
        fenced = False
        verified = False

        # Attempt both independent containment controls even if one fails.
        # This minimizes the exposure window during a partial outage.
        try:
            self._credential_store.revoke_session(session_id)
            store_revoked = True
        except Exception:
            pass

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
                )
            except Exception:
                self._record_failure(actor, session_id, terminated)
                raise SessionRevocationError(
                    "Revocation completed but its audit record could not be confirmed"
                ) from None
            return SessionRevocationResult(
                session_id=session_id,
                terminated_backend_count=terminated,
                verified=True,
            )

        self._record_failure(actor, session_id, terminated)
        raise SessionRevocationError(
            "Human database session revocation is incomplete; retry and verify"
        ) from None

    def _record_failure(
        self, actor: AuthenticatedPrincipal, session_id: UUID, terminated: int
    ) -> None:
        # Do not serialize provider exceptions, credentials, or backend details.
        try:
            self._audit.record_event(
                event_type="human_database_session_revocation_attempt",
                actor_subject=actor.subject,
                session_id=session_id,
                outcome="incomplete",
                terminated_backend_count=terminated,
            )
        except Exception:
            # Audit unavailability must not turn a partial revocation into success.
            pass
