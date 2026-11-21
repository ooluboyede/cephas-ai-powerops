from __future__ import annotations

from datetime import datetime

import pytest

from powerops.secrets import (
    EnvironmentSecretProvider,
    SecretAccessDeniedError,
    SecretNotFoundError,
    SecretValue,
    SecretVersionError,
    resolve_database_secret,
)


def test_environment_provider_retrieves_secret_with_redacted_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POWEROPS_TEST_DATABASE_DSN", "postgresql://secret-value")
    provider = EnvironmentSecretProvider(allow_insecure=True)
    secret = resolve_database_secret(provider, "env://POWEROPS_TEST_DATABASE_DSN")
    assert secret.reveal() == "postgresql://secret-value"
    assert secret.version == "unversioned"
    assert "secret-value" not in repr(secret)
    assert "secret-value" not in str(secret)


def test_environment_provider_is_rejected_outside_dev_test() -> None:
    with pytest.raises(SecretAccessDeniedError):
        EnvironmentSecretProvider(allow_insecure=False)


def test_environment_provider_rejects_unsupported_reference() -> None:
    provider = EnvironmentSecretProvider(allow_insecure=True)
    with pytest.raises(SecretNotFoundError):
        provider.get_secret("env://bad-name")


def test_environment_provider_rejects_missing_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POWEROPS_MISSING_SECRET", raising=False)
    provider = EnvironmentSecretProvider(allow_insecure=True)
    with pytest.raises(SecretNotFoundError):
        provider.get_secret("env://POWEROPS_MISSING_SECRET")


def test_environment_provider_does_not_claim_version_pinning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POWEROPS_TEST_DATABASE_DSN", "postgresql://secret-value")
    provider = EnvironmentSecretProvider(allow_insecure=True)
    with pytest.raises(SecretVersionError):
        provider.get_secret("env://POWEROPS_TEST_DATABASE_DSN", version="v17")


def test_secret_value_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError):
        SecretValue(
            _value="x",
            reference="ref",
            version="v1",
            retrieved_at=datetime(2026, 1, 1),
        )
