"""Customer-pinned Ed25519 verification for credential-store revocation receipts.

The receipt is a provider-neutral, signed statement. It contains no credential
material. The public key must be provisioned out-of-band by the customer.
"""
from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


@dataclass(frozen=True, slots=True)
class CredentialRevocationReceipt:
    session_id: UUID
    issuer: str
    key_id: str
    revoked_at: datetime
    outcome: str
    signature_b64: str


class CredentialRevocationReceiptVerifier(Protocol):
    def verify(
        self, receipt: CredentialRevocationReceipt, *, session_id: UUID
    ) -> bool:
        """Verify a provider receipt against customer-pinned trust material."""


def canonical_receipt_payload(receipt: CredentialRevocationReceipt) -> bytes:
    """Return the exact stable byte representation signed by the provider."""
    if (
        not isinstance(receipt.session_id, UUID)
        or not isinstance(receipt.issuer, str)
        or not receipt.issuer.startswith("https://")
        or len(receipt.issuer) > 300
        or not isinstance(receipt.key_id, str)
        or not receipt.key_id
        or len(receipt.key_id) > 128
        or not isinstance(receipt.revoked_at, datetime)
        or receipt.revoked_at.tzinfo is None
        or receipt.revoked_at.utcoffset() is None
        or receipt.outcome != "revoked"
        or not isinstance(receipt.signature_b64, str)
        or len(receipt.signature_b64) > 256
    ):
        raise ValueError("Invalid credential revocation receipt")
    payload = {
        "issuer": receipt.issuer,
        "key_id": receipt.key_id,
        "outcome": receipt.outcome,
        "revoked_at": receipt.revoked_at.astimezone(UTC).isoformat(
            timespec="microseconds"
        ),
        "session_id": str(receipt.session_id),
        "version": 1,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


class Ed25519CredentialRevocationReceiptVerifier:
    """Verify signed receipts using customer-configured issuer/key-id pins."""

    def __init__(self, *, trusted_keys: dict[tuple[str, str], bytes]) -> None:
        if not trusted_keys:
            raise ValueError("At least one customer-pinned receipt key is required")
        parsed: dict[tuple[str, str], Ed25519PublicKey] = {}
        for identity, raw_key in trusted_keys.items():
            if (
                not isinstance(identity, tuple)
                or len(identity) != 2
                or not all(isinstance(value, str) and value for value in identity)
                or not isinstance(raw_key, bytes)
                or len(raw_key) != 32
            ):
                raise ValueError("Invalid customer receipt trust configuration")
            parsed[identity] = Ed25519PublicKey.from_public_bytes(raw_key)
        self._trusted_keys = parsed

    def verify(
        self, receipt: CredentialRevocationReceipt, *, session_id: UUID
    ) -> bool:
        if not isinstance(receipt, CredentialRevocationReceipt):
            return False
        if receipt.session_id != session_id:
            return False
        key = self._trusted_keys.get((receipt.issuer, receipt.key_id))
        if key is None:
            return False
        try:
            signature = base64.b64decode(receipt.signature_b64, validate=True)
            if len(signature) != 64:
                return False
            key.verify(signature, canonical_receipt_payload(receipt))
        except (InvalidSignature, ValueError, TypeError, binascii.Error):
            return False
        return True
