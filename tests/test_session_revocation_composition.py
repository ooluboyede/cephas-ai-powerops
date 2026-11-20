from __future__ import annotations

from base64 import b64encode
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from powerops.auth import AuthenticatedPrincipal
from powerops.credential_revocation_attestation import (
    CredentialRevocationReceipt,
    Ed25519CredentialRevocationReceiptVerifier,
    canonical_receipt_payload,
)
from powerops.postgres_principal_verification import (
    PostgresPrincipalVerificationError,
)
from powerops.session_revocation_composition import (
    build_human_session_revocation_coordinator,
)


def principal_row(
    login, *, can_retire=False, can_terminate=False, can_count=False, can_audit=False
):
    return {
        "session_user": login,
        "current_user": login,
        "session_control_member": False,
        "revocation_auditor_member": False,
        "can_retire": can_retire,
        "can_terminate": can_terminate,
        "can_count": can_count,
        "can_audit": can_audit,
        "registry_direct_access": False,
        "backend_audit_direct_access": False,
        "revocation_audit_direct_access": False,
    }


class FakeCursor:
    def __init__(self, event_log, row):
        self.event_log = event_log
        self.row = row

    def execute(self, sql, params):
        if "jsonb_build_object" in sql:
            return
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
        return (self.row,) if isinstance(self.row, dict) else self.row

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
        self.signing_key = Ed25519PrivateKey.generate()

    def get_session_scope(self, session_id):
        return (
            UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        )

    def revoke_session(self, session_id):
        self.event_log.append(("credential_revoke", session_id))
        receipt = CredentialRevocationReceipt(
            session_id=session_id,
            issuer="https://vault.customer.example",
            key_id="vault-key-2026-01",
            revoked_at=datetime.now(UTC),
            outcome="revoked",
            signature_b64="AA==",
        )
        signature = self.signing_key.sign(canonical_receipt_payload(receipt))
        return CredentialRevocationReceipt(
            session_id=receipt.session_id,
            issuer=receipt.issuer,
            key_id=receipt.key_id,
            revoked_at=receipt.revoked_at,
            outcome=receipt.outcome,
            signature_b64=b64encode(signature).decode("ascii"),
        )


def receipt_verifier(store):
    public_key = store.signing_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return Ed25519CredentialRevocationReceiptVerifier(
        trusted_keys={("https://vault.customer.example", "vault-key-2026-01"): public_key}
    )


def test_composed_coordinator_verifies_actual_principals_before_revocation():
    session_id = uuid4()
    events = []
    calls = {"provisioner": 0, "termination": 0, "audit": 0}

    def provisioner_factory():
        calls["provisioner"] += 1
        if calls["provisioner"] == 1:
            row = principal_row("powerops_provisioner", can_retire=True)
        else:
            row = (None,)
        return FakeConnection(events, row)

    def termination_factory():
        calls["termination"] += 1
        if calls["termination"] == 1:
            row = principal_row("powerops_termination", can_terminate=True, can_count=True)
        elif calls["termination"] == 2:
            row = (2, 0, True)
        else:
            row = (0,)
        return FakeConnection(events, row)

    def audit_factory():
        calls["audit"] += 1
        row = principal_row("powerops_audit", can_audit=True) if calls["audit"] == 1 else (101,)
        return FakeConnection(events, row)

    store = FakeCredentialStore(events)
    coordinator = build_human_session_revocation_coordinator(
        credential_store=store,
        provisioner_connection_factory=provisioner_factory,
        termination_connection_factory=termination_factory,
        audit_connection_factory=audit_factory,
        expected_provisioner_login="powerops_provisioner",
        expected_termination_login="powerops_termination",
        expected_audit_login="powerops_audit",
        credential_receipt_verifier=receipt_verifier(store),
    )
    actor = AuthenticatedPrincipal(
        subject="oidc|session-revoker",
        tenant_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        business_unit_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        roles=frozenset({"powerops_session_revoker"}),
        issuer="https://issuer.example",
    )

    result = coordinator.revoke(actor=actor, session_id=session_id)

    assert result.session_id == session_id
    assert result.terminated_backend_count == 2
    assert result.verified is True
    assert [event[0] for event in events] == [
        "credential_revoke", "fence", "terminate", "verify", "audit"
    ]


def test_composition_fails_closed_when_factory_authenticates_as_wrong_login():
    events = []

    def factory(login, **privileges):
        return lambda: FakeConnection(events, principal_row(login, **privileges))

    store = FakeCredentialStore(events)
    with pytest.raises(PostgresPrincipalVerificationError):
        build_human_session_revocation_coordinator(
            credential_store=store,
            provisioner_connection_factory=factory("unexpected_role", can_retire=True),
            termination_connection_factory=factory(
                "powerops_termination", can_terminate=True, can_count=True
            ),
            audit_connection_factory=factory("powerops_audit", can_audit=True),
            expected_provisioner_login="powerops_provisioner",
            expected_termination_login="powerops_termination",
            expected_audit_login="powerops_audit",
        )


def test_composition_fails_closed_when_audit_role_has_direct_table_access():
    events = []

    def factory(login, *, direct=False, **privileges):
        row = principal_row(login, **privileges)
        row["revocation_audit_direct_access"] = direct
        return lambda: FakeConnection(events, row)

    store = FakeCredentialStore(events)
    with pytest.raises(PostgresPrincipalVerificationError):
        build_human_session_revocation_coordinator(
            credential_store=store,
            provisioner_connection_factory=factory(
                "powerops_provisioner", can_retire=True
            ),
            termination_connection_factory=factory(
                "powerops_termination", can_terminate=True, can_count=True
            ),
            audit_connection_factory=factory(
                "powerops_audit", can_audit=True, direct=True
            ),
            expected_provisioner_login="powerops_provisioner",
            expected_termination_login="powerops_termination",
            expected_audit_login="powerops_audit",
        )
