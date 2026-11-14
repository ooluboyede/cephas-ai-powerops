"""Bounded PostgreSQL connection pool isolated to one BU-scoped DB identity.

A pool belongs to exactly one configured database login. Every checkout resolves
and compares the authenticated database scope before application SQL is allowed.
Credential rotation validates a replacement pool before atomically swapping it.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status


class ScopedConnectionPool:
    """A bounded pool that must never be shared across tenant/BU credentials."""

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 8,
        timeout: float = 5.0,
        close_timeout: float = 30.0,
    ) -> None:
        if not dsn.strip():
            raise ValueError("A PostgreSQL DSN is required")
        if min_size < 1 or max_size < min_size or timeout <= 0 or close_timeout <= 0:
            raise ValueError("Invalid PostgreSQL pool bounds or timeout")
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._timeout = timeout
        self._close_timeout = close_timeout
        self._lock = RLock()
        self._pool: Any | None = None
        self._closed = False

    def _new_pool(self, dsn: str) -> Any:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            conninfo=dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            timeout=self._timeout,
            kwargs={
                "row_factory": dict_row,
                "connect_timeout": max(1, int(self._timeout)),
            },
            open=False,
        )
        try:
            pool.open(wait=True)
        except Exception:
            pool.close(timeout=self._close_timeout)
            raise
        return pool

    @staticmethod
    def _verify_scope(connection: Any, tenant_id: UUID, business_unit_id: UUID) -> None:
        identity = connection.execute(
            """
            SELECT tenant_id, scope_kind, business_unit_id
            FROM powerops_security.resolve_authenticated_scope()
            """
        ).fetchone()
        if (
            identity is None
            or identity["scope_kind"] != "business_unit"
            or identity["tenant_id"] != tenant_id
            or identity["business_unit_id"] != business_unit_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Database login scope does not match authenticated business unit",
            )

    def _get_pool_and_connection(self) -> tuple[Any, Any]:
        with self._lock:
            if self._closed:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="PostgreSQL connection pool is closed",
                )
            if self._pool is None:
                try:
                    self._pool = self._new_pool(self._dsn)
                except Exception:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="PostgreSQL connection pool is unavailable",
                    ) from None
            pool = self._pool
            try:
                connection = pool.getconn(timeout=self._timeout)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="PostgreSQL connection pool is unavailable",
                ) from None
            return pool, connection

    @contextmanager
    def connection(self, tenant_id: UUID, business_unit_id: UUID) -> Iterator[Any]:
        pool, connection = self._get_pool_and_connection()
        try:
            # A transaction encloses scope verification and the complete unit of
            # work. It commits on success and rolls back on every exception before
            # the connection is returned to the pool.
            with connection.transaction():
                self._verify_scope(connection, tenant_id, business_unit_id)
                yield connection
        finally:
            pool.putconn(connection)

    def rotate_credentials(
        self,
        new_dsn: str,
        *,
        expected_tenant_id: UUID,
        expected_business_unit_id: UUID,
    ) -> None:
        """Validate replacement credentials before switching new checkouts to them."""
        if not new_dsn.strip():
            raise ValueError("A PostgreSQL DSN is required")
        candidate = self._new_pool(new_dsn)
        try:
            connection = candidate.getconn(timeout=self._timeout)
            try:
                with connection.transaction():
                    self._verify_scope(
                        connection, expected_tenant_id, expected_business_unit_id
                    )
            finally:
                candidate.putconn(connection)
        except Exception:
            candidate.close(timeout=self._close_timeout)
            raise

        with self._lock:
            if self._closed:
                candidate.close(timeout=self._close_timeout)
                raise RuntimeError("Cannot rotate credentials after pool shutdown")
            previous = self._pool
            self._pool = candidate
            self._dsn = new_dsn

        # The old pool is drained after the swap. Existing borrowers may finish;
        # no new checkout can obtain the old pool through this manager.
        if previous is not None:
            previous.close(timeout=self._close_timeout)

    def close(self) -> None:
        """Stop new checkouts and drain the current pool."""
        with self._lock:
            self._closed = True
            previous = self._pool
            self._pool = None
        if previous is not None:
            previous.close(timeout=self._close_timeout)
