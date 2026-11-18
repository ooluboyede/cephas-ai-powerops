from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from powerops.human_session_issuer import (
    HumanSessionCredentialConflict,
    HumanSessionCredentialStoreUnavailable,
    StoredHumanSessionCredential,
)


class MockVaultCredentialStore:
    """Test-only adapter modelling immutable vault record semantics.

    This class is not production storage and provides no encryption, durable
    persistence, provider IAM, or audit guarantees.
    """

    def __init__(self) -> None:
        self._records: dict[UUID, StoredHumanSessionCredential] = {}
        self._revoked: set[UUID] = set()
        self.unavailable = False

    def _check_available(self) -> None:
        if self.unavailable:
            raise HumanSessionCredentialStoreUnavailable(
                "Mock credential store is unavailable"
            )

    def store_session(
        self,
        *,
        session_id: UUID,
        issuer: str,
        subject: str,
        tenant_id: UUID,
        business_unit_id: UUID,
        finance_operator: bool,
        finance_verifier: bool,
        database_role: str,
        certificate_pem: str,
        private_key_pem: str,
        expires_at: datetime,
    ) -> None:
        self._check_available()
        record = StoredHumanSessionCredential(
            session_id=session_id,
            issuer=issuer,
            subject=subject,
            tenant_id=tenant_id,
            business_unit_id=business_unit_id,
            finance_operator=finance_operator,
            finance_verifier=finance_verifier,
            database_role=database_role,
            certificate_pem=certificate_pem,
            private_key_pem=private_key_pem,
            expires_at=expires_at,
        )
        existing = self._records.get(session_id)
        if existing is not None:
            if existing != record:
                raise HumanSessionCredentialConflict(
                    "Session UUID is already bound to a different credential"
                )
            return
        self._records[session_id] = record

    def get_session(self, session_id: UUID) -> StoredHumanSessionCredential | None:
        self._check_available()
        if session_id in self._revoked:
            return None
        record = self._records.get(session_id)
        if record is None or record.expires_at <= datetime.now(UTC):
            return None
        return record

    def revoke_session(self, session_id: UUID) -> None:
        self._check_available()
        self._revoked.add(session_id)


def credential(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "session_id": uuid4(),
        "issuer": "https://identity.customer.example",
        "subject": "finance.user.17",
        "tenant_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        "business_unit_id": UUID("a1000000-0000-4000-8000-000000000001"),
        "finance_operator": False,
        "finance_verifier": True,
        "database_role": "pwr_finance_user_17",
        "certificate_pem": "-----BEGIN CERTIFICATE-----\\nmock-certificate",
        "private_key_pem": "-----BEGIN PRIVATE KEY-----\\nmock-private-key",
        "expires_at": datetime.now(UTC) + timedelta(minutes=2),
    }
    values.update(overrides)
    return values


def store(store_adapter: MockVaultCredentialStore, values: dict[str, object]) -> None:
    store_adapter.store_session(**values)  # type: ignore[arg-type]


def test_identical_session_write_is_idempotent() -> None:
    adapter = MockVaultCredentialStore()
    values = credential()

    store(adapter, values)
    store(adapter, values)

    assert adapter.get_session(values["session_id"]) is not None


@pytest.mark.parametrize(
    "changed_field",
    [
        "issuer",
        "subject",
        "tenant_id",
        "business_unit_id",
        "finance_operator",
        "database_role",
        "certificate_pem",
        "private_key_pem",
        "expires_at",
    ],
)
def test_session_uuid_cannot_be_rebound_to_changed_credential(
    changed_field: str,
) -> None:
    adapter = MockVaultCredentialStore()
    original = credential()
    store(adapter, original)
    changed = dict(original)
    if changed_field == "finance_operator":
        changed[changed_field] = True
        changed["finance_verifier"] = False
    elif changed_field == "expires_at":
        changed[changed_field] = datetime.now(UTC) + timedelta(minutes=3)
    elif changed_field in {"tenant_id", "business_unit_id"}:
        changed[changed_field] = uuid4()
    elif changed_field == "issuer":
        changed[changed_field] = "https://different.identity.example"
    elif changed_field == "certificate_pem":
        changed[changed_field] = "-----BEGIN CERTIFICATE-----\\nchanged-certificate"
    elif changed_field == "private_key_pem":
        changed[changed_field] = "-----BEGIN PRIVATE KEY-----\\nchanged-private-key"
    elif changed_field == "database_role":
        changed[changed_field] = "pwr_changed_role"
    else:
        changed[changed_field] = f"changed-{changed_field}"

    with pytest.raises(HumanSessionCredentialConflict):
        store(adapter, changed)

    assert adapter.get_session(original["session_id"]) is not None  # type: ignore[arg-type]


def test_exact_uuid_lookup_never_falls_back_to_another_session() -> None:
    adapter = MockVaultCredentialStore()
    first = credential()
    store(adapter, first)

    assert adapter.get_session(uuid4()) is None


def test_expired_credential_is_not_retrievable() -> None:
    adapter = MockVaultCredentialStore()
    values = credential(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    store(adapter, values)

    assert adapter.get_session(values["session_id"]) is None  # type: ignore[arg-type]


def test_revocation_is_idempotent_and_scoped_to_exact_session() -> None:
    adapter = MockVaultCredentialStore()
    first = credential()
    second = credential(subject="finance.user.18")
    store(adapter, first)
    store(adapter, second)

    adapter.revoke_session(first["session_id"])  # type: ignore[arg-type]
    adapter.revoke_session(first["session_id"])  # type: ignore[arg-type]

    assert adapter.get_session(first["session_id"]) is None  # type: ignore[arg-type]
    assert adapter.get_session(second["session_id"]) is not None  # type: ignore[arg-type]


def test_store_outage_fails_closed_without_secret_values_in_error() -> None:
    adapter = MockVaultCredentialStore()
    values = credential()
    adapter.unavailable = True

    with pytest.raises(HumanSessionCredentialStoreUnavailable) as error:
        store(adapter, values)

    assert values["private_key_pem"] not in str(error.value)
    assert values["certificate_pem"] not in str(error.value)
