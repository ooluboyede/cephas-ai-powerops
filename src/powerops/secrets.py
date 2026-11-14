"""Provider-neutral, fail-closed secret retrieval contracts.

Secret material is deliberately kept out of repr(), logs, API models and database
metadata. The environment provider is for local development/test only.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable


class SecretProviderError(RuntimeError):
    """Base class for safe-to-report secret provider failures."""


class SecretNotFoundError(SecretProviderError):
    """The requested secret reference or version does not exist."""


class SecretAccessDeniedError(SecretProviderError):
    """The workload identity is not authorized to read the requested secret."""


class SecretVersionError(SecretProviderError):
    """The requested secret version is unavailable or invalid."""


@dataclass(frozen=True, slots=True)
class SecretValue:
    """Secret value with redacted representation and non-secret version metadata."""

    _value: str
    reference: str
    version: str
    retrieved_at: datetime

    def __post_init__(self) -> None:
        if not self._value:
            raise ValueError("Secret value must not be empty")
        if not self.reference or not self.version:
            raise ValueError("Secret reference and version metadata are required")
        if self.retrieved_at.tzinfo is None:
            raise ValueError("Secret retrieval timestamp must be timezone-aware")

    def reveal(self) -> str:
        """Return the secret only to trusted server-side code."""
        return self._value

    def __repr__(self) -> str:
        return (
            f"SecretValue(reference={self.reference!r}, version={self.version!r}, "
            "value=[REDACTED])"
        )

    def __str__(self) -> str:
        return "[REDACTED]"


@runtime_checkable
class SecretProvider(Protocol):
    """Adapter contract implemented by a customer-selected secret manager."""

    provider_name: str

    def get_secret(
        self, reference: str, *, version: str | None = None
    ) -> SecretValue:
        """Retrieve a current or explicitly pinned secret version."""


_ENV_REFERENCE = re.compile(r"^env://([A-Z][A-Z0-9_]*)$")


class EnvironmentSecretProvider:
    """Development/test-only provider backed by process environment variables."""

    provider_name = "environment"

    def __init__(self, *, allow_insecure: bool) -> None:
        if not allow_insecure:
            raise SecretAccessDeniedError(
                "Environment secret provider is disabled outside development/test"
            )

    def get_secret(
        self, reference: str, *, version: str | None = None
    ) -> SecretValue:
        match = _ENV_REFERENCE.fullmatch(reference)
        if match is None:
            raise SecretNotFoundError("Unsupported environment secret reference")
        if version not in (None, "current"):
            raise SecretVersionError("Environment secrets do not support pinned versions")
        key = match.group(1)
        value = os.environ.get(key)
        if value is None or not value.strip():
            raise SecretNotFoundError("Configured environment secret is unavailable")
        return SecretValue(
            _value=value,
            reference=reference,
            version="unversioned",
            retrieved_at=datetime.now(timezone.utc),
        )


def resolve_database_secret(
    provider: SecretProvider, reference: str, *, version: str | None = None
) -> SecretValue:
    """Retrieve and validate a database credential without logging its contents."""
    secret = provider.get_secret(reference, version=version)
    if not secret.reveal().strip():
        raise SecretNotFoundError("Database credential is empty")
    return secret
