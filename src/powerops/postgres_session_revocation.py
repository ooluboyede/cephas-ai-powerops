"""Separate-credential PostgreSQL control-plane adapter for exact session revocation.

The provisioner connection may execute only the 0014 admission-fence function.
The termination connection must be a separately authenticated customer
control-plane identity explicitly granted EXECUTE on the 0015 termination
function and the minimal read privileges needed for exact backend verification.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from powerops.session_revocation import SessionRevocationError


ConnectionFactory = Callable[[], Any]


class PsycopgSessionBackendRevocationControl:
    """Execute exact-session fencing and termination on separate DB identities.

    The factories must be independently configured by the customer. The first
    identity is authorized for retire_human_session_login(uuid, text); the
    second is authorized for terminate_human_session_backends(uuid) and exact
    registry/backend verification. Neither factory accepts caller DSNs or
    session-selected role names.
    """

    _RETIREMENT_REASON = "powerops_exact_session_revocation"

    def __init__(
        self,
        *,
        provisioner_connection_factory: ConnectionFactory,
        termination_connection_factory: ConnectionFactory,
    ) -> None:
        if not callable(provisioner_connection_factory) or not callable(
            termination_connection_factory
        ):
            raise ValueError("Separate PostgreSQL control connection factories are required")
        if provisioner_connection_factory is termination_connection_factory:
            raise ValueError("Fence and termination credentials must use separate factories")
        self._provisioner_connection_factory = provisioner_connection_factory
        self._termination_connection_factory = termination_connection_factory

    @staticmethod
    def _close(connection: Any) -> None:
        try:
            connection.close()
        except Exception:
            # The operation's commit/verification result, not close diagnostics,
            # determines the public outcome.
            pass

    @classmethod
    def _execute_committed(
        cls, factory: ConnectionFactory, sql: str, params: tuple[Any, ...]
    ) -> Any:
        connection = None
        try:
            connection = factory()
            cursor = connection.cursor()
            try:
                cursor.execute(sql, params)
                row = cursor.fetchone()
            finally:
                cursor.close()
            # An acknowledged COMMIT is required before the caller may proceed
            # to backend termination. If acknowledgement is lost, retry is safe:
            # the database function is idempotent for an already-retired UUID.
            connection.commit()
            return row
        except Exception:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise SessionRevocationError(
                "Customer PostgreSQL revocation control operation failed"
            ) from None
        finally:
            if connection is not None:
                cls._close(connection)

    def fence_session(self, session_id: UUID) -> None:
        if not isinstance(session_id, UUID):
            raise SessionRevocationError("A valid exact session UUID is required")
        self._execute_committed(
            self._provisioner_connection_factory,
            "SELECT powerops_security.retire_human_session_login(%s, %s)",
            (str(session_id), self._RETIREMENT_REASON),
        )

    @staticmethod
    def _termination_values(row: Any) -> tuple[int, int, bool]:
        if isinstance(row, Mapping):
            keys = {
                "terminated_backend_count",
                "remaining_backend_count",
                "complete",
            }
            if set(row.keys()) != keys:
                raise SessionRevocationError(
                    "Customer PostgreSQL returned an invalid termination result"
                )
            terminated = row["terminated_backend_count"]
            remaining = row["remaining_backend_count"]
            complete = row["complete"]
        elif isinstance(row, (tuple, list)) and len(row) == 3:
            terminated, remaining, complete = row
        else:
            raise SessionRevocationError(
                "Customer PostgreSQL returned an invalid termination result"
            )
        if (
            isinstance(terminated, bool)
            or not isinstance(terminated, int)
            or terminated < 0
            or isinstance(remaining, bool)
            or not isinstance(remaining, int)
            or remaining < 0
            or not isinstance(complete, bool)
            or complete is not (remaining == 0)
        ):
            raise SessionRevocationError(
                "Customer PostgreSQL returned an invalid termination result"
            )
        return terminated, remaining, complete

    def terminate_session_backends(self, session_id: UUID) -> int:
        if not isinstance(session_id, UUID):
            raise SessionRevocationError("A valid exact session UUID is required")
        row = self._execute_committed(
            self._termination_connection_factory,
            "SELECT terminated_backend_count, remaining_backend_count, complete "
            "FROM powerops_security.terminate_human_session_backends(%s)",
            (str(session_id),),
        )
        terminated, remaining, complete = self._termination_values(row)
        # An incomplete but well-formed result is not an adapter error: return
        # the signal count so the coordinator can independently query the
        # remaining exact-session backend count and record an honest partial
        # outcome. The coordinator will never report success when count > 0.
        return terminated

    def active_session_backend_count(self, session_id: UUID) -> int:
        if not isinstance(session_id, UUID):
            raise SessionRevocationError("A valid exact session UUID is required")
        row = self._execute_committed(
            self._termination_connection_factory,
            "SELECT powerops_security.count_human_session_backends(%s) "
            "AS remaining_backend_count",
            (str(session_id),),
        )
        if isinstance(row, Mapping):
            if set(row.keys()) != {"remaining_backend_count"}:
                raise SessionRevocationError(
                    "Customer PostgreSQL returned an invalid backend count"
                )
            count = row["remaining_backend_count"]
        elif isinstance(row, (tuple, list)) and len(row) == 1:
            count = row[0]
        else:
            raise SessionRevocationError(
                "Customer PostgreSQL returned an invalid backend count"
            )
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise SessionRevocationError(
                "Customer PostgreSQL returned an invalid backend count"
            )
        return count
