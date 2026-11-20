from __future__ import annotations

from uuid import uuid4

import pytest

from powerops.postgres_session_revocation_audit import PostgresSessionRevocationAudit
from powerops.session_revocation import SessionRevocationError
from powerops.session_revocation_composition import (
    build_human_session_revocation_coordinator,
)


class Cursor:
    def __init__(self, row=(41,)):
        self.row = row
        self.executed = None
        self.closed = False

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, row=(41,), *, fail_commit=False):
        self.cursor_instance = Cursor(row)
        self.fail_commit = fail_commit
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("synthetic secret MUST_NOT_LEAK")

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def event(session_id):
    return {
        "event_type": "human_database_session_revoked",
        "actor_subject": "oidc|reviewer-42",
        "session_id": session_id,
        "outcome": "verified",
        "terminated_backend_count": 2,
        "credential_revoked": True,
        "admission_fenced": True,
        "backend_termination_verified": True,
    }


def test_audit_sink_calls_only_append_function_and_commits():
    session_id = uuid4()
    connection = Connection()
    audit = PostgresSessionRevocationAudit(connection_factory=lambda: connection)

    audit.record_event(**event(session_id))

    sql, params = connection.cursor_instance.executed
    assert "record_human_session_revocation_audit" in sql
    assert params == (
        "human_database_session_revoked",
        "oidc|reviewer-42",
        str(session_id),
        "verified",
        2,
        True,
        True,
        True,
    )
    assert connection.commits == 1
    assert connection.closed


def test_audit_sink_rejects_invalid_or_contradictory_event_before_connecting():
    called = False

    def factory():
        nonlocal called
        called = True
        return Connection()

    audit = PostgresSessionRevocationAudit(connection_factory=factory)
    payload = event(uuid4())
    payload["terminated_backend_count"] = True
    with pytest.raises(SessionRevocationError):
        audit.record_event(**payload)
    assert not called

    payload = event(uuid4())
    payload["backend_termination_verified"] = False
    with pytest.raises(SessionRevocationError):
        audit.record_event(**payload)
    assert not called


def test_audit_sink_commit_uncertainty_is_generic_and_fails_closed():
    connection = Connection(fail_commit=True)
    audit = PostgresSessionRevocationAudit(connection_factory=lambda: connection)

    with pytest.raises(SessionRevocationError) as error:
        audit.record_event(**event(uuid4()))

    assert "MUST_NOT_LEAK" not in str(error.value)
    assert connection.rollbacks == 1
    assert connection.closed


def test_audit_sink_requires_database_confirmation():
    connection = Connection(row=None)
    audit = PostgresSessionRevocationAudit(connection_factory=lambda: connection)
    with pytest.raises(SessionRevocationError):
        audit.record_event(**event(uuid4()))
    assert connection.rollbacks == 1


def test_composition_requires_three_distinct_connection_factories():
    def one():
        return Connection()

    def two():
        return Connection()

    with pytest.raises(ValueError, match="must be separate"):
        build_human_session_revocation_coordinator(
            credential_store=object(),
            provisioner_connection_factory=one,
            termination_connection_factory=two,
            audit_connection_factory=one,
        )


def test_composition_builds_coordinator_with_injected_credential_store():
    credential_store = object()
    def one():
        return Connection()

    def two():
        return Connection()

    def three():
        return Connection()

    coordinator = build_human_session_revocation_coordinator(
        credential_store=credential_store,
        provisioner_connection_factory=one,
        termination_connection_factory=two,
        audit_connection_factory=three,
    )
    assert coordinator is not None
