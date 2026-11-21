from __future__ import annotations

from base64 import b64encode
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from powerops.credential_revocation_attestation import (
    CredentialRevocationReceipt,
    Ed25519CredentialRevocationReceiptVerifier,
    canonical_receipt_payload,
)


def signed_receipt(private_key, session_id):
    receipt = CredentialRevocationReceipt(
        session_id=session_id,
        issuer="https://vault.customer.example",
        key_id="vault-key-2026-01",
        revoked_at=datetime.now(UTC),
        outcome="revoked",
        signature_b64="AA==",
    )
    signature = private_key.sign(canonical_receipt_payload(receipt))
    return replace(receipt, signature_b64=b64encode(signature).decode("ascii"))


def build_verifier(private_key):
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return Ed25519CredentialRevocationReceiptVerifier(
        trusted_keys={
            ("https://vault.customer.example", "vault-key-2026-01"): public_key
        }
    )


def test_accepts_valid_receipt_bound_to_exact_session():
    key = Ed25519PrivateKey.generate()
    session_id = uuid4()
    receipt = signed_receipt(key, session_id)

    assert build_verifier(key).verify(receipt, session_id=session_id) is True


def test_rejects_receipt_for_different_session():
    key = Ed25519PrivateKey.generate()
    receipt = signed_receipt(key, uuid4())

    assert build_verifier(key).verify(receipt, session_id=uuid4()) is False


def test_rejects_tampered_revocation_timestamp():
    key = Ed25519PrivateKey.generate()
    receipt = signed_receipt(key, uuid4())
    tampered = replace(
        receipt, revoked_at=receipt.revoked_at + timedelta(seconds=1)
    )

    assert build_verifier(key).verify(tampered, session_id=receipt.session_id) is False


def test_rejects_unknown_customer_pinned_issuer_or_key_id():
    key = Ed25519PrivateKey.generate()
    receipt = signed_receipt(key, uuid4())
    wrong_issuer = replace(receipt, issuer="https://untrusted.example")

    assert build_verifier(key).verify(
        wrong_issuer, session_id=receipt.session_id
    ) is False


def test_rejects_non_revoked_outcome():
    key = Ed25519PrivateKey.generate()
    receipt = signed_receipt(key, uuid4())
    not_revoked = replace(receipt, outcome="pending")

    assert build_verifier(key).verify(
        not_revoked, session_id=receipt.session_id
    ) is False
