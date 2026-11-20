from __future__ import annotations

from uuid import uuid4

from powerops.auth import AuthenticatedPrincipal
from powerops.session_revocation_composition import (
    build_human_session_revocation_coordinator,
)


class FakeCursor:
    def __init__(self, event_log, row):
        self.event_log = event_log
        self.row = row

    def execute(self, sql, params):
        if "retire_human_session_login" in sql:
            operation = "fence"
        elif "terminate_human_session_backends" in sql:
            operation = "terminate"
        elif "count_human_session_backends" in sql:
            operation = "verify"
        elif "record_human_session_revocation_audit" in sql:
            operation = "audit"
        else:
            raise AssertionError("Unexpected SQL operation")
        self.event_log.append((operation, params))

    def fetchone(self):
        return self.row

    def close(self):
        return None


class FakeConnection:
    def __init__(self, event_log, row):
        self.cursor_instance = FakeCursor(event_log, row)

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


class FakeCredentialStore:
    def __init__(self, event_log):
        self.event_log = event_log

    def revoke_session(self, session_id):
        self.event_log.append(("credential_revoke", session_id))


def test_composed_coordinator_executes_full_verified_revocation_sequence():
    session_id = uuid4()
    events = []

    def provisioner_factory():
        return FakeConnection(events, (None,))

    def termination_factory():
        # First call is termination; second call verifies no live backends.
        row = (2, 0, True) if sum(e[0] == "terminate" for e in events) == 0 else (0,)
        return FakeConnection(events, row)

    def audit_factory():
        return FakeConnection(events, (101,))

    coordinator = build_human_session_revocation_coordinator(
        credential_store=FakeCredentialStore(events),
        provisioner_connection_factory=provisioner_factory,
        termination_connection_factory=termination_factory,
        audit_connection_factory=audit_factory,
    )
    actor = AuthenticatedPrincipal(
        subject="oidc|session-revoker",
        tenant_id=uuid4(),
        business_unit_id=uuid4(),
        roles=frozenset({"powerops_session_revoker"}),
        issuer="https://issuer.example",
    )

    result = coordinator.revoke(actor=actor, session_id=session_id)

    assert result.session_id == session_id
    assert result.terminated_backend_count == 2
    assert result.verified is True
    assert [event[0] for event in events] == [
        "credential_revoke",
        "fence",
        "terminate",
        "verify",
        "audit",
    ]
    assert events[1][1] == (str(session_id), "powerops_exact_session_revocation")
    assert events[2][1] == (str(session_id),)
    assert events[3][1] == (str(session_id),)
    assert events[4][1][0] == "human_database_session_revoked"
    assert events[4][1][2] == str(session_id)
