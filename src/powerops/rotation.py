"""Version-pinned credential rotation orchestration for one BU-scoped service.

This coordinator has no scheduler and no provider SDK. A deployment-owned trigger
calls rotate_to_version() when its secret provider publishes an approved version.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Protocol
from uuid import UUID

from powerops.secrets import SecretProvider


class CredentialRotationError(RuntimeError):
    """Safe-to-report rotation failure; never includes a credential or DSN."""


class CredentialRotationAuditError(CredentialRotationError):
    """Rotation outcome could not be durably recorded by the audit sink."""


@dataclass(frozen=True, slots=True)
class RotationAuditEvent:
    reference: str
    version: str
    provider: str
    tenant_id: UUID
    business_unit_id: UUID
    outcome: str
    occurred_at: datetime


class CredentialRepository(Protocol):
    """Narrow repository contract; implementation owns pool swap and DB identity checks."""

    def rotate_credentials(
        self,
        new_dsn: str,
        *,
        expected_tenant_id: UUID,
        expected_business_unit_id: UUID,
    ) -> None:
        """Validate candidate credentials and replace the scoped pool atomically."""


class RotationAuditSink(Protocol):
    """Customer-owned durable audit destination for non-secret rotation metadata."""

    def record(self, event: RotationAuditEvent) -> None:
        """Persist the event durably or raise without logging secret material."""


@dataclass(frozen=True, slots=True)
class RotationResult:
    reference: str
    version: str
    provider: str
    rotated_at: datetime
    tenant_id: UUID
    business_unit_id: UUID


class CredentialRotationService:
    """Rotate credentials for one fixed BU identity and one fixed secret reference."""

    def __init__(
        self,
        *,
        provider: SecretProvider,
        secret_reference: str,
        repository: CredentialRepository,
        tenant_id: UUID,
        business_unit_id: UUID,
        audit_sink: RotationAuditSink,
    ) -> None:
        if not secret_reference.strip():
            raise ValueError("A deployment-bound secret reference is required")
        self._provider = provider
        self._reference = secret_reference
        self._repository = repository
        self._tenant_id = tenant_id
        self._business_unit_id = business_unit_id
        self._audit = audit_sink
        self._lock = Lock()
        self._active_version: str | None = None

    @property
    def active_version(self) -> str | None:
        """In-process last-successful version; durable truth belongs in audit storage."""
        return self._active_version

    def rotate_to_version(self, version: str) -> RotationResult:
        """Retrieve, verify and activate one immutable secret version.

        The version must be explicit. "latest" aliases and unversioned development
        secrets are not accepted because they cannot provide a reproducible rotation.
        """
        if not version.strip() or version.casefold() in {
            "latest",
            "current",
            "unversioned",
        }:
            raise CredentialRotationError("An immutable secret version is required")

        with self._lock:
            try:
                secret = self._provider.get_secret(self._reference, version=version)
            except Exception:
                try:
                    self._audit.record(
                        RotationAuditEvent(
                            reference=self._reference,
                            version=version,
                            provider=self._provider.provider_name,
                            tenant_id=self._tenant_id,
                            business_unit_id=self._business_unit_id,
                            outcome="failed",
                            occurred_at=datetime.now(timezone.utc),
                        )
                    )
                except Exception:
                    raise CredentialRotationAuditError(
                        "Secret retrieval failed and failure-audit recording also failed; "
                        "active credentials are unchanged"
                    ) from None
                raise CredentialRotationError(
                    "Secret retrieval failed; active database credentials are unchanged"
                ) from None
            if secret.reference != self._reference or secret.version != version:
                raise CredentialRotationError(
                    "Secret provider returned a different reference or version"
                )
            candidate_dsn = secret.reveal()
            if not candidate_dsn.strip() or any(
                character in candidate_dsn for character in ("\x00", "\r", "\n")
            ):
                raise CredentialRotationError("Secret is not a valid database credential")

            try:
                self._repository.rotate_credentials(
                    candidate_dsn,
                    expected_tenant_id=self._tenant_id,
                    expected_business_unit_id=self._business_unit_id,
                )
            except Exception:
                # Suppress provider/driver exceptions because some drivers include
                # connection strings in exception text. The existing pool is expected
                # to remain active when candidate validation fails.
                try:
                    self._audit.record(
                        RotationAuditEvent(
                            reference=self._reference,
                            version=version,
                            provider=self._provider.provider_name,
                            tenant_id=self._tenant_id,
                            business_unit_id=self._business_unit_id,
                            outcome="failed",
                            occurred_at=datetime.now(timezone.utc),
                        )
                    )
                except Exception:
                    raise CredentialRotationAuditError(
                        "Rotation failed and failure-audit recording also failed; "
                        "active credentials remain unchanged"
                    ) from None
                raise CredentialRotationError(
                    "Replacement credential validation failed; active credentials "
                    "remain unchanged"
                ) from None

            rotated_at = datetime.now(timezone.utc)
            self._active_version = version
            event = RotationAuditEvent(
                reference=self._reference,
                version=version,
                provider=self._provider.provider_name,
                tenant_id=self._tenant_id,
                business_unit_id=self._business_unit_id,
                outcome="succeeded",
                occurred_at=rotated_at,
            )
            try:
                self._audit.record(event)
            except Exception:
                # The repository has already swapped pools. Do not report a generic
                # rotation failure that might cause an unsafe blind retry.
                raise CredentialRotationAuditError(
                    "Credentials were rotated, but durable success-audit recording "
                    "failed; investigate audit delivery before another rotation"
                ) from None

            return RotationResult(
                reference=self._reference,
                version=version,
                provider=self._provider.provider_name,
                rotated_at=rotated_at,
                tenant_id=self._tenant_id,
                business_unit_id=self._business_unit_id,
            )
