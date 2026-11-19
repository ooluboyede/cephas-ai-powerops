from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from powerops.auth import AuthenticatedPrincipal
from powerops.session_revocation import (
    HumanSessionRevocationCoordinator,
    SessionRevocationError,
)


class Store:
    def __init__(self):
        self.revoked = set()
        self.fail = False

    def revoke_session(self, session_id):
        if self.fail:
            raise RuntimeError("synthetic provider secret MUST_NOT_LEAK")
        self.revoked.add(session_id)


class BackendControl:
    def __init__(self, active):
        self.active = set(active)
        self.fenced = set()
        self.events = []
        self.fail_terminate = False

    def fence_session(self, session_id):
        self.events.append(("fence", session_id))
        self.fenced.add(session_id)

    def terminate_session_backends(self, session_id):
        self.events.append(("terminate", session_id))
        if self.fail_terminate:
            raise RuntimeError("synthetic database password MUST_NOT_LEAK")
        count = 1 if session_id in self.active else 0
        self.active.discard(session_id)
        return count

    def active_session_backend_count(self, session_id):
        self.events.append(("verify", session_id))
        return int(session_id in self.active)


class Audit:
    def __init__(self):
        self.events = []
        self.fail = False

    def record_event(self, **event):
        if self.fail:
            raise RuntimeError("audit sink unavailable")
        self.events.append(event)


def principal(*, authorized=True):
    return AuthenticatedPrincipal(
        subject="security.operator",
        tenant_id=uuid4(),
        business_unit_id=uuid4(),
        roles=frozenset(
            {"powerops_session_revoker"} if authorized else {"finance_verifier"}
        ),
        issuer="https://identity.customer.example",
    )


def coordinator(store, backend, audit):
    return HumanSessionRevocationCoordinator(
        credential_store=store, backend_control=backend, audit=audit
    )


def test_revokes_only_exact_session_and_verifies_backend_termination():
    first, second = uuid4(), uuid4()
    store = Store()
    backend = BackendControl({first, second})
    audit = Audit()

    result = coordinator(store, backend, audit).revoke(
        actor=principal(), session_id=first
    )

    assert result.verified is True
    assert result.terminated_backend_count == 1
    assert first in store.revoked
    assert first not in backend.active
    assert second in backend.active
    assert backend.events == [
        ("fence", first), ("terminate", first), ("verify", first)
    ]
    assert audit.events[-1]["outcome"] == "verified"
    assert audit.events[-1]["session_id"] == first
    assert "MUST_NOT_LEAK" not in repr(audit.events)


def test_unauthorized_actor_cannot_revoke():
    session_id = uuid4()
    store, backend, audit = Store(), BackendControl({session_id}), Audit()

    with pytest.raises(SessionRevocationError, match="not authorized"):
        coordinator(store, backend, audit).revoke(
            actor=principal(authorized=False), session_id=session_id
        )

    assert not store.revoked
    assert not backend.fenced
    assert not backend.events


def test_backend_termination_failure_is_not_reported_as_success_and_is_retryable():
    session_id = uuid4()
    store = Store()
    backend = BackendControl({session_id})
    backend.fail_terminate = True
    audit = Audit()
    service = coordinator(store, backend, audit)

    with pytest.raises(SessionRevocationError, match="incomplete"):
        service.revoke(actor=principal(), session_id=session_id)

    assert session_id in backend.fenced
    assert session_id in store.revoked
    assert session_id in backend.active
    assert audit.events[-1]["outcome"] == "incomplete"

    backend.fail_terminate = False
    result = service.revoke(actor=principal(), session_id=session_id)
    assert result.verified is True
    assert session_id not in backend.active


def test_store_outage_keeps_session_fenced_and_fails_closed():
    session_id = uuid4()
    store = Store()
    store.fail = True
    backend = BackendControl({session_id})
    audit = Audit()

    with pytest.raises(SessionRevocationError, match="incomplete"):
        coordinator(store, backend, audit).revoke(
            actor=principal(), session_id=session_id
        )

    assert session_id in backend.fenced
    assert session_id in backend.active
    assert ("terminate", session_id) not in backend.events
    assert "MUST_NOT_LEAK" not in str(audit.events)


def test_already_terminated_session_is_idempotently_verified():
    session_id = uuid4()
    store = Store()
    backend = BackendControl(set())
    audit = Audit()

    result = coordinator(store, backend, audit).revoke(
        actor=principal(), session_id=session_id
    )

    assert result.verified is True
    assert result.terminated_backend_count == 0
    assert session_id in store.revoked


def test_nonzero_remaining_backend_prevents_success():
    session_id = uuid4()

    class NonTerminatingBackend(BackendControl):
        def terminate_session_backends(self, exact_session_id):
            self.events.append(("terminate", exact_session_id))
            return 0

    store = Store()
    backend = NonTerminatingBackend({session_id})
    audit = Audit()

    with pytest.raises(SessionRevocationError, match="unverified"):
        coordinator(store, backend, audit).revoke(
            actor=principal(), session_id=session_id
        )

    assert audit.events[-1]["outcome"] == "incomplete"


def test_audit_failure_does_not_report_revocation_success():
    session_id = uuid4()
    store = Store()
    backend = BackendControl({session_id})
    audit = Audit()
    audit.fail = True

    with pytest.raises(SessionRevocationError, match="incomplete"):
        coordinator(store, backend, audit).revoke(
            actor=principal(), session_id=session_id
        )

    assert session_id not in backend.active
