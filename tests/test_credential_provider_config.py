from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from powerops.credential_provider_config import (
    HumanSessionProviderConfig,
    ProviderConfigurationError,
    validate_human_session_provider_config,
)


def valid_config() -> dict[str, object]:
    return {
        "provider_id": "customer_adapter",
        "endpoint": "https://secrets.example.internal",
        "ca_bundle_path": "/etc/powerops/trust/customer-ca.pem",
        "namespace": "powerops-prod",
        "secret_store": "human-session-kv",
        "credential_path_prefix": "powerops/human-sessions",
        "certificate_issuer_ref": "pki/issuers/postgres-client",
        "certificate_role_ref": "roles/powerops-human",
        "workload_identity_method": "workload_identity",
        "workload_identity_audience": "powerops-human-session",
        "request_timeout_seconds": 5.0,
    }


def test_provider_config_accepts_non_secret_customer_metadata() -> None:
    config = validate_human_session_provider_config(valid_config())
    assert isinstance(config, HumanSessionProviderConfig)
    assert config.endpoint == "https://secrets.example.internal"
    assert config.credential_path_prefix == "powerops/human-sessions"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://secrets.example.internal",
        "https://user:password@secrets.example.internal",
        "https://secrets.example.internal?token=secret",
        "https://",
        "https://secrets.example.internal#fragment",
    ],
)
def test_provider_config_rejects_insecure_or_credential_bearing_endpoint(
    endpoint: str,
) -> None:
    values = valid_config()
    values["endpoint"] = endpoint
    with pytest.raises(ProviderConfigurationError):
        validate_human_session_provider_config(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ca_bundle_path", "relative/ca.pem"),
        ("ca_bundle_path", "/etc/powerops/../secret/ca.pem"),
        ("ca_bundle_path", "C:\\\\powerops\\\\..\\\\secret\\\\ca.pem"),
        ("namespace", "../other"),
        ("secret_store", "mount/*"),
        ("credential_path_prefix", "powerops/../other"),
        ("credential_path_prefix", "powerops/*"),
        ("certificate_issuer_ref", "issuer with spaces"),
        ("certificate_role_ref", "roles/*"),
        ("workload_identity_method", "Workload Identity"),
        ("workload_identity_audience", ""),
        ("provider_id", "Vault"),
    ],
)
def test_provider_config_rejects_invalid_references_and_paths(
    field: str, value: str
) -> None:
    values = valid_config()
    values[field] = value
    with pytest.raises(ProviderConfigurationError):
        validate_human_session_provider_config(values)


def test_provider_config_rejects_unknown_fields_including_secret_fields() -> None:
    values = valid_config()
    values["token"] = "must-not-be-configured"
    with pytest.raises(ProviderConfigurationError) as error:
        validate_human_session_provider_config(values)
    assert "must-not-be-configured" not in str(error.value)


def test_provider_config_rejects_invalid_timeout() -> None:
    values = valid_config()
    values["request_timeout_seconds"] = 0
    with pytest.raises(ProviderConfigurationError):
        validate_human_session_provider_config(values)


def test_model_is_immutable_and_does_not_expose_secret_fields() -> None:
    values = deepcopy(valid_config())
    config = validate_human_session_provider_config(values)
    with pytest.raises(ValidationError):
        config.provider_id = "changed"  # type: ignore[misc]
    assert "token" not in config.model_fields
