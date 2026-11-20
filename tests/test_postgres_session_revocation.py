from __future__ import annotations

from uuid import uuid4

import pytest

from powerops.postgres_session_revocation import PsycopgSessionBackendRevocationControl
from powerops.session_revocation import SessionRevocationError


class Cursor:
    def __init__(self, row):
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
    def __init__(self, row, *, fail_commit=False):
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
            raise RuntimeError("synthetic uncertain commit secret MUST_NOT_LEAK")

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def make_control(provisioner, termination):
    return PsycopgSessionBackendRevocationControl(
        provisioner_connection_factory=lambda: provisioner,
        termination_connection_factory=lambda: termination,
    )


def test_fence_uses_provisioner_identity_and_commits_before_return():
    session_id = uuid4()
    provisioner = Connection((None,))
    termination = Connection((0, 0, True))
    control = make_control(provisioner, termination)

    control.fence_session(session_id)

    sql, params = provisioner.cursor_instance.executed
    assert "retire_human_session_login" in sql
    assert params == (str(session_id), "powerops_exact_session_revocation")
    assert provisioner.commits == 1
    assert provisioner.closed
    assert termination.commits == 0


def test_termination_uses_separate_identity_and_requires_complete_result():
    session_id = uuid4()
    provisioner = Connection((None,))
    termination = Connection((2, 0, True))
    control = make_control(provisioner, termination)

    assert control.terminate_session_backends(session_id) == 2
    sql, params = termination.cursor_instance.executed
    assert "terminate_human_session_backends" in sql
    assert params == (str(session_id),)
    assert termination.commits == 1
    assert termination.closed
    assert provisioner.commits == 0


@pytest.mark.parametrize(
    "row",
    [
        (True, 0, True),
        (-1, 0, True),
        (0, -1, False),
        (0, 0, 1),
        (0, 1, True),
        None,
        (0, 0),
        {"terminated_backend_count": 0, "remaining_backend_count": 0},
    ],
)
def test_malformed_or_incomplete_termination_result_fails_closed(row):
    control = make_control(Connection((None,)), Connection(row))
    with pytest.raises(SessionRevocationError):
        control.terminate_session_backends(uuid4())


def test_backend_verification_is_exact_session_and_rejects_boolean_count():
    session_id = uuid4()
    termination = Connection({"remaining_backend_count": 0})
    control = make_control(Connection((None,)), termination)

    assert control.active_session_backend_count(session_id) == 0
    sql, params = termination.cursor_instance.executed
    assert "registry.session_id = %s" in sql
    assert "activity.backend_start = registry.backend_start" in sql
    assert params == (str(session_id),)

    bad = make_control(Connection((None,)), Connection((True,)))
    with pytest.raises(SessionRevocationError):
        bad.active_session_backend_count(session_id)


def test_fence_commit_uncertainty_fails_closed_without_secret_disclosure():
    provisioner = Connection((None,), fail_commit=True)
    control = make_control(provisioner, Connection((0, 0, True)))

    with pytest.raises(SessionRevocationError) as error:
        control.fence_session(uuid4())

    assert "MUST_NOT_LEAK" not in str(error.value)
    assert provisioner.rollbacks == 1
    assert provisioner.closed


def test_same_factory_cannot_be_used_for_both_privilege_domains():
    factory = lambda: Connection((None,))
    with pytest.raises(ValueError, match="separate factories"):
        PsycopgSessionBackendRevocationControl(
            provisioner_connection_factory=factory,
            termination_connection_factory=factory,
        )


def test_incomplete_but_well_formed_termination_is_left_for_coordinator_verification():
    session_id = uuid4()
    termination = Connection((1, 2, False))
    control = make_control(Connection((None,)), termination)

    assert control.terminate_session_backends(session_id) == 1
    assert termination.commits == 1
