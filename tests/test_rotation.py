from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from powerops.rotation import (
    CredentialRotationAuditError,
    CredentialRotationError,
    CredentialRotationService,
    RotationAuditEvent,
)
from powerops.secrets import SecretNotFoundError, SecretValue

TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BU = UUID("a1000000-0000-4000-8000-000000000001")
REFERENCE = "vault://customer/powerops/bu-a/database"


class FakeProvider:
    provider_name = "test-provider"

    def __init__(self, *, value: str = "postgresql://candidate-secret", returned_version: str = "v2"):
        self.value = value
        self.returned_version = returned_version
        self.calls: list[tuple[str, str | None]] = []
        self.fail = False

    def get_secret(self, reference: str, *, version: str | None = None) -> SecretValue:
        self.calls.append((reference, version))
        if self.fail:
            raise SecretNotFoundError("not found")
        return SecretValue(
            _value=self.value,
            reference=reference,
            version=self.returned_version,
            retrieved_at=datetime.now(timezone.utc),
        )


class FakeRepository:
    def __init__(self) -> None:
        self.rotations: list[tuple[str, UUID, UUID]] = []
        self.fail = False

    def rotate_credentials(
        self,
        dsn: str,
        *,
        expected_tenant_id: UUID,
        expected_business_unit_id: UUID,
    ) -> None:
        if self.fail:
            raise RuntimeError("driver error included postgresql://candidate-secret")
        self.rotations.append((dsn, expected_tenant_id, expected_business_unit_id))


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[RotationAuditEvent] = []
        self.fail = False

    def record(self, event: RotationAuditEvent) -> None:
        if self.fail:
            raise RuntimeError("audit unavailable")
        self.events.append(event)


def service(provider=None, repository=None, audit=None):
    provider = provider or FakeProvider()
    repository = repository or FakeRepository()
    audit = audit or FakeAudit()
    return (
        CredentialRotationService(
            provider=provider,
            secret_reference=REFERENCE,
            repository=repository,
            tenant_id=TENANT,
            business_unit_id=BU,
            audit_sink=audit,
        ),
        provider,
        repository,
        audit,
    )


def test_successful_rotation_is_version_pinned_and_audited_without_secret() -> None:
    rotation, provider, repository, audit = service()
    result = rotation.rotate_to_version("v2")
    assert provider.calls == [(REFERENCE, "v2")]
    assert repository.rotations == [("postgresql://candidate-secret", TENANT, BU)]
    assert rotation.active_version == "v2"
    assert result.version == "v2"
    assert len(audit.events) == 1
    event = audit.events[0]
    assert event.outcome == "succeeded"
    assert event.reference == REFERENCE
    assert "candidate-secret" not in repr(event)


@pytest.mark.parametrize("version", ["", "latest", "current", "unversioned"])
def test_rotation_requires_immutable_version(version: str) -> None:
    rotation, provider, repository, audit = service()
    with pytest.raises(CredentialRotationError):
        rotation.rotate_to_version(version)
    assert provider.calls == []
    assert repository.rotations == []
    assert audit.events == []


def test_provider_failure_preserves_active_credentials() -> None:
    provider = FakeProvider()
    provider.fail = True
    rotation, _, repository, audit = service(provider=provider)
    with pytest.raises(CredentialRotationError, match="retrieval failed"):
        rotation.rotate_to_version("v2")
    assert repository.rotations == []
    assert rotation.active_version is None
    assert audit.events == []


def test_provider_cannot_substitute_version_or_reference() -> None:
    provider = FakeProvider(returned_version="v3")
    rotation, _, repository, audit = service(provider=provider)
    with pytest.raises(CredentialRotationError, match="different reference or version"):
        rotation.rotate_to_version("v2")
    assert repository.rotations == []
    assert audit.events == []


def test_database_identity_validation_failure_is_redacted_and_audited() -> None:
    repository = FakeRepository()
    repository.fail = True
    rotation, _, _, audit = service(repository=repository)
    with pytest.raises(CredentialRotationError) as error:
        rotation.rotate_to_version("v2")
    assert "candidate-secret" not in str(error.value)
    assert rotation.active_version is None
    assert audit.events[0].outcome == "failed"


def test_post_swap_audit_failure_is_explicitly_distinguished() -> None:
    audit = FakeAudit()
    audit.fail = True
    rotation, _, repository, _ = service(audit=audit)
    with pytest.raises(CredentialRotationAuditError, match="Credentials were rotated"):
        rotation.rotate_to_version("v2")
    assert len(repository.rotations) == 1
    assert rotation.active_version == "v2"


def test_invalid_dsn_control_characters_rejected() -> None:
    provider = FakeProvider(value="postgresql://candidate\nsecret")
    rotation, _, repository, _ = service(provider=provider)
    with pytest.raises(CredentialRotationError, match="not a valid database credential"):
        rotation.rotate_to_version("v2")
    assert repository.rotations == []
