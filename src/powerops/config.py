"""Validated application configuration."""

from functools import lru_cache

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings; secrets must be supplied through the deployment environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CEPHAS AI PowerOps"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: SecretStr | None = None
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def blank_database_url_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_oidc_configuration(self) -> "Settings":
        oidc_values = (self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url)
        if any(value is not None for value in oidc_values) and not all(
            isinstance(value, str) and value.strip() for value in oidc_values
        ):
            raise ValueError("OIDC_ISSUER, OIDC_AUDIENCE and OIDC_JWKS_URL must be set together")
        if self.oidc_issuer and self.oidc_jwks_url:
            from urllib.parse import urlparse

            for value in (self.oidc_issuer, self.oidc_jwks_url):
                parsed = urlparse(value)
                local_http = parsed.scheme == "http" and parsed.hostname in {
                    "localhost",
                    "127.0.0.1",
                }
                if parsed.scheme != "https" and not local_http:
                    raise ValueError("OIDC issuer and JWKS URLs must use HTTPS")
                if not parsed.netloc:
                    raise ValueError("OIDC issuer and JWKS URLs must be absolute URLs")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings instance."""
    return Settings()
