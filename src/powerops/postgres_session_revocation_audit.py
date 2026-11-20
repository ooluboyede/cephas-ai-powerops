"""PostgreSQL append-only audit sink for human-session revocation."""
from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any
from uuid import UUID

from powerops.credential_revocation_attestation import (
    CredentialRevocationReceipt,
    canonical_receipt_payload,
)
from powerops.session_revocation import SessionRevocationError


AuditConnectionFactory = Callable[[], Any]


class PostgresSessionRevocationAudit:
    """Persist secret-free coordinator events through a dedicated audit identity.

    The customer DBA must grant this login EXECUTE on the migration 0016
    SECURITY DEFINER function only. It must not receive direct table DML.
    """

    def __init__(self, *, connection_factory: AuditConnectionFactory) -> None:
        if not callable(connection_factory):
            raise ValueError("A dedicated PostgreSQL audit connection factory is required")
        self._connection_factory = connection_factory

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
        if (
            not isinstance(event_type, str)
            or event_type not in {
                "human_database_session_revoked",
                "human_database_session_revocation_attempt",
            }
            or not isinstance(actor_subject, str)
            or not actor_subject.strip()
            or len(actor_subject) > 200
            or not isinstance(session_id, UUID)
            or not isinstance(outcome, str)
            or outcome not in {"verified", "incomplete"}
            or isinstance(terminated_backend_count, bool)
            or not isinstance(terminated_backend_count, int)
            or terminated_backend_count < 0
            or not all(
                isinstance(value, bool)
                for value in (
                    credential_revoked,
                    admission_fenced,
                    backend_termination_verified,
                )
            )
        ):
            raise SessionRevocationError("Invalid session revocation audit event")

        if outcome == "verified" and not (
            credential_revoked and admission_fenced and backend_termination_verified
        ):
            raise SessionRevocationError("Verified audit outcome contradicts containment state")

        if credential_receipt is not None:
            try:
                receipt_payload = json.loads(
                    canonical_receipt_payload(credential_receipt).decode("ascii")
                )
                receipt_signature = credential_receipt.signature_b64
            except (TypeError, ValueError, UnicodeError):
                raise SessionRevocationError(
                    "Invalid credential revocation receipt evidence"
                ) from None
        else:
            receipt_payload = None
            receipt_signature = None

        if outcome == "verified" and (receipt_payload is None or receipt_signature is None):
            raise SessionRevocationError(
                "Verified audit outcome requires signed credential receipt evidence"
            )

        connection = None
        try:
            connection = self._connection_factory()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    SELECT powerops_security.record_human_session_revocation_audit(
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        event_type,
                        actor_subject,
                        str(session_id),
                        outcome,
                        terminated_backend_count,
                        credential_revoked,
                        admission_fenced,
                        backend_termination_verified,
                        receipt_payload,
                        receipt_signature,
                    ),
                )
                row = cursor.fetchone()
            finally:
                cursor.close()
            if (
                not isinstance(row, (tuple, list))
                or len(row) != 1
                or isinstance(row[0], bool)
                or not isinstance(row[0], int)
                or row[0] <= 0
            ):
                raise SessionRevocationError(
                    "Customer PostgreSQL did not confirm the revocation audit record"
                )
            connection.commit()
        except SessionRevocationError:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        except Exception:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise SessionRevocationError(
                "Customer PostgreSQL revocation audit is unavailable"
            ) from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
