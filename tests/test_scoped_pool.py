from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from uuid import UUID

import pytest
from fastapi import HTTPException

from powerops.scoped_pool import ScopedConnectionPool

TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BUSINESS_UNIT = UUID("a1000000-0000-4000-8000-000000000001")
OTHER_TENANT = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
OTHER_BUSINESS_UNIT = UUID("b1000000-0000-4000-8000-000000000001")


class FakeConnection:
    def __init__(self, tenant_id: UUID, business_unit_id: UUID) -> None:
        self.identity = {
            "tenant_id": tenant_id,
            "scope_kind": "business_unit",
            "business_unit_id": business_unit_id,
        }
        self.scope_checks = 0
        self.commits = 0
        self.rollbacks = 0

    def execute(self, _query: str) -> FakeConnection:
        self.scope_checks += 1
        return self

    def fetchone(self) -> dict[str, object]:
        return self.identity

    @contextmanager
    def transaction(self):
        try:
            yield
        except Exception:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1


class FakePool:
    instances: list[FakePool] = []
    identities: dict[str, tuple[UUID, UUID]] = {}

    def __init__(self, *, conninfo: str, **_kwargs: object) -> None:
        tenant_id, business_unit_id = self.identities[conninfo]
        self.connection = FakeConnection(tenant_id, business_unit_id)
        self.closed = False
        self.returned = 0
        self.opened = False
        self.instances.append(self)

    def open(self, *, wait: bool) -> None:
        assert wait is True
        self.opened = True

    def getconn(self, *, timeout: float) -> FakeConnection:
        assert timeout > 0
        if self.closed:
            raise RuntimeError("pool closed")
        return self.connection

    def putconn(self, _connection: FakeConnection) -> None:
        self.returned += 1

    def close(self, *, timeout: float) -> None:
        assert timeout > 0
        self.closed = True


@pytest.fixture
def fake_psycopg(monkeypatch: pytest.MonkeyPatch) -> None:
    FakePool.instances = []
    FakePool.identities = {
        "bu-a-dsn": (TENANT, BUSINESS_UNIT),
        "wrong-bu-dsn": (OTHER_TENANT, OTHER_BUSINESS_UNIT),
        "rotated-bu-dsn": (TENANT, BUSINESS_UNIT),
    }
    psycopg_rows = types.ModuleType("psycopg.rows")
    psycopg_rows.dict_row = object()
    psycopg = types.ModuleType("psycopg")
    psycopg.__path__ = []  # type: ignore[attr-defined]
    pool_module = types.ModuleType("psycopg_pool")
    pool_module.ConnectionPool = FakePool  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psycopg", psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.rows", psycopg_rows)
    monkeypatch.setitem(sys.modules, "psycopg_pool", pool_module)


def test_checkout_verifies_scope_and_commits_transaction(fake_psycopg: None) -> None:
    pool = ScopedConnectionPool("bu-a-dsn")
    with pool.connection(TENANT, BUSINESS_UNIT) as connection:
        assert connection.scope_checks == 1
    fake = FakePool.instances[0]
    assert fake.connection.commits == 1
    assert fake.connection.rollbacks == 0
    assert fake.returned == 1
    pool.close()


def test_scope_mismatch_rolls_back_and_returns_connection(fake_psycopg: None) -> None:
    pool = ScopedConnectionPool("bu-a-dsn")
    with pytest.raises(HTTPException) as error:
        with pool.connection(OTHER_TENANT, OTHER_BUSINESS_UNIT):
            pytest.fail("Application SQL must not run after a scope mismatch")
    assert error.value.status_code == 403
    fake = FakePool.instances[0]
    assert fake.connection.rollbacks == 1
    assert fake.returned == 1
    pool.close()


def test_failed_rotation_does_not_replace_active_pool(fake_psycopg: None) -> None:
    pool = ScopedConnectionPool("bu-a-dsn")
    # Establish the original pool first; a failed candidate must not replace it.
    with pool.connection(TENANT, BUSINESS_UNIT):
        pass
    with pytest.raises(HTTPException) as error:
        pool.rotate_credentials(
            "wrong-bu-dsn",
            expected_tenant_id=TENANT,
            expected_business_unit_id=BUSINESS_UNIT,
        )
    assert error.value.status_code == 403
    original, candidate = FakePool.instances
    assert original.closed is False
    assert candidate.closed is True
    with pool.connection(TENANT, BUSINESS_UNIT):
        pass
    assert original.returned == 2
    pool.close()


def test_valid_rotation_swaps_then_drains_previous_pool(fake_psycopg: None) -> None:
    pool = ScopedConnectionPool("bu-a-dsn")
    with pool.connection(TENANT, BUSINESS_UNIT):
        pass
    pool.rotate_credentials(
        "rotated-bu-dsn",
        expected_tenant_id=TENANT,
        expected_business_unit_id=BUSINESS_UNIT,
    )
    original, replacement = FakePool.instances
    assert original.closed is True
    assert replacement.closed is False
    with pool.connection(TENANT, BUSINESS_UNIT):
        pass
    assert replacement.returned == 2  # rotation probe + application checkout
    pool.close()


def test_close_prevents_new_pool_creation(fake_psycopg: None) -> None:
    pool = ScopedConnectionPool("bu-a-dsn")
    with pool.connection(TENANT, BUSINESS_UNIT):
        pass
    pool.close()
    with pytest.raises(HTTPException) as error:
        with pool.connection(TENANT, BUSINESS_UNIT):
            pytest.fail("A closed pool must not be recreated")
    assert error.value.status_code == 503
    assert len(FakePool.instances) == 1



def test_health_snapshot_reports_lifecycle_and_checkout_counters(
    fake_psycopg: None,
) -> None:
    pool = ScopedConnectionPool("bu-a-dsn", max_size=4)
    initial = pool.health_snapshot()
    assert initial["state"] == "not_initialized"
    assert initial["active_checkouts"] == 0

    with pool.connection(TENANT, BUSINESS_UNIT):
        active = pool.health_snapshot()
        assert active["state"] == "healthy"
        assert active["active_checkouts"] == 1
        assert active["total_checkouts"] == 1

    after = pool.health_snapshot()
    assert after["active_checkouts"] == 0
    assert after["total_checkouts"] == 1
    assert after["pool_max_size"] == 4
    assert "dsn" not in after
    assert "tenant_id" not in after

    pool.rotate_credentials(
        "rotated-bu-dsn",
        expected_tenant_id=TENANT,
        expected_business_unit_id=BUSINESS_UNIT,
    )
    assert pool.health_snapshot()["successful_rotations"] == 1
    pool.close()
    assert pool.health_snapshot()["state"] == "closed"
