from __future__ import annotations

import json
from base64 import b64encode
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from powerops.credential_revocation_attestation import (
    CredentialRevocationReceipt,
    Ed25519CredentialRevocationReceiptVerifier,
    canonical_receipt_payload,
)
from powerops.postgres_session_revocation_audit import PostgresSessionRevocationAudit
from powerops.session_revocation import SessionRevocationError
from powerops.session_revocation_composition import (
    build_human_session_revocation_coordinator,
)


_SIGNING_KEY = Ed25519PrivateKey.generate()


def signed_receipt(session_id):
    receipt = CredentialRevocationReceipt(
        session_id=session_id,
        issuer="https://vault.customer.example",
        key_id="audit-test-key",
        revoked_at=datetime.now(UTC),
        outcome="revoked",
        signature_b64="AA==",
    )
    signature = _SIGNING_KEY.sign(canonical_receipt_payload(receipt))
    return CredentialRevocationReceipt(
        session_id=receipt.session_id,
        issuer=receipt.issuer,
        key_id=receipt.key_id,
        revoked_at=receipt.revoked_at,
        outcome=receipt.outcome,
        signature_b64=b64encode(signature).decode("ascii"),
    )


def receipt_verifier():
    public_key = _SIGNING_KEY.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return Ed25519CredentialRevocationReceiptVerifier(
        trusted_keys={("https://vault.customer.example", "audit-test-key"): public_key}
    )


def identity_row(login, *, retire=False, terminate=False, count=False, audit=False):
    return {
        "session_user": login,
        "current_user": login,
        "session_control_member": False,
        "revocation_auditor_member": False,
        "pg_read_all_stats_member": False,
        "pg_monitor_member": False,
        "pg_signal_backend_member": False,
        "can_retire": retire,
        "can_terminate": terminate,
        "can_count": count,
        "can_audit": audit,
        "registry_direct_access": False,
        "session_binding_direct_access": False,
        "actor_binding_direct_access": False,
        "backend_audit_direct_access": False,
        "pg_stat_direct_access": False,
        "revocation_audit_direct_access": False,
    }


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
        "credential_receipt": signed_receipt(session_id),
    }


def test_audit_sink_calls_only_append_function_and_commits():
    session_id = uuid4()
    connection = Connection()
    audit = PostgresSessionRevocationAudit(connection_factory=lambda: connection)
    payload = event(session_id)

    audit.record_event(**payload)

    sql, params = connection.cursor_instance.executed
    assert "record_human_session_revocation_audit" in sql
    assert params[:8] == (
        "human_database_session_revoked",
        "oidc|reviewer-42",
        str(session_id),
        "verified",
        2,
        True,
        True,
        True,
    )
    assert "%s::jsonb" in sql
    assert json.loads(params[8])["session_id"] == str(session_id)
    assert params[9] == payload["credential_receipt"].signature_b64
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

    with pytest.raises(ValueError, match="separate factories"):
        build_human_session_revocation_coordinator(
            credential_store=object(),
            provisioner_connection_factory=one,
            termination_connection_factory=two,
            audit_connection_factory=one,
            expected_provisioner_login="powerops_provisioner",
            expected_termination_login="powerops_termination",
            expected_audit_login="powerops_audit",
            credential_receipt_verifier=receipt_verifier(),
        )


def test_composition_builds_coordinator_with_injected_credential_store():
    credential_store = object()

    def one():
        return Connection(row=identity_row("powerops_provisioner", retire=True))

    def two():
        return Connection(
            row=identity_row("powerops_termination", terminate=True, count=True)
        )

    def three():
        return Connection(row=identity_row("powerops_audit", audit=True))

    coordinator = build_human_session_revocation_coordinator(
        credential_store=credential_store,
        provisioner_connection_factory=one,
        termination_connection_factory=two,
        audit_connection_factory=three,
        expected_provisioner_login="powerops_provisioner",
        expected_termination_login="powerops_termination",
        expected_audit_login="powerops_audit",
        credential_receipt_verifier=receipt_verifier(),
    )
    assert coordinator is not None
