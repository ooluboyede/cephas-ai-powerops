"""Provider-neutral configuration contract for human-session credential adapters.

This module validates non-secret deployment metadata only. It does not create a
provider client, authenticate to a secrets platform, or prove customer IAM.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class ProviderConfigurationError(ValueError):
    """Safe, non-secret configuration validation failure."""


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{1,62}$")
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")
_AUDIENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")


class HumanSessionProviderConfig(BaseModel):
    """Non-secret, provider-neutral settings for a customer credential adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    provider_id: str = Field(min_length=2, max_length=63)
    endpoint: str = Field(min_length=9, max_length=2048)
    ca_bundle_path: str = Field(min_length=3, max_length=1024)
    namespace: str = Field(min_length=1, max_length=128)
    secret_store: str = Field(min_length=1, max_length=128)
    credential_path_prefix: str = Field(min_length=1, max_length=512)
    certificate_issuer_ref: str = Field(min_length=1, max_length=255)
    certificate_role_ref: str = Field(min_length=1, max_length=255)
    workload_identity_method: str = Field(min_length=2, max_length=63)
    workload_identity_audience: str = Field(min_length=1, max_length=255)
    request_timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    @field_validator("provider_id", "workload_identity_method")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("must be a lowercase identifier")
        return value

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("endpoint must be an HTTPS URL without embedded credentials")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("endpoint port is invalid") from exc
        return value.rstrip("/")

    @field_validator("ca_bundle_path")
    @classmethod
    def validate_ca_bundle_path(cls, value: str) -> str:
        if not (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()):
            raise ValueError("CA bundle path must be absolute")
        if any(part == ".." for part in value.replace(chr(92), "/").split("/")):
            raise ValueError("CA bundle path must not traverse parent directories")
        return value

    @field_validator("namespace", "secret_store", "certificate_issuer_ref", "certificate_role_ref")
    @classmethod
    def validate_references(cls, value: str) -> str:
        if not _REFERENCE.fullmatch(value) or ".." in value or "*" in value:
            raise ValueError("reference contains unsupported characters")
        return value.strip("/")

    @field_validator("credential_path_prefix")
    @classmethod
    def validate_credential_path(cls, value: str) -> str:
        normalized = value.strip("/")
        parts = normalized.split("/")
        if (
            not normalized
            or any(part in {"", ".", ".."} for part in parts)
            or any("*" in part for part in parts)
            or not all(re.fullmatch(r"[A-Za-z0-9._-]{1,100}", part) for part in parts)
        ):
            raise ValueError("credential path prefix is invalid")
        return normalized

    @field_validator("workload_identity_audience")
    @classmethod
    def validate_audience(cls, value: str) -> str:
        if not _AUDIENCE.fullmatch(value):
            raise ValueError("workload identity audience is invalid")
        return value

    @model_validator(mode="after")
    def reject_reserved_provider_ids(self) -> HumanSessionProviderConfig:
        if self.provider_id in {"environment", "local", "none"}:
            raise ValueError("development-only provider identifiers are not valid here")
        return self


def validate_human_session_provider_config(
    values: dict[str, Any],
) -> HumanSessionProviderConfig:
    """Validate untrusted config input and raise a message safe for application logs.

    Do not log the original mapping or Pydantic's detailed ValidationError: those
    may contain user-supplied values. This wrapper deliberately emits no values.
    """
    try:
        return HumanSessionProviderConfig.model_validate(values)
    except ValidationError as exc:
        raise ProviderConfigurationError(
            "Human-session provider configuration is invalid; review the deployment schema"
        ) from exc
