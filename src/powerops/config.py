"""Validated application configuration."""

from functools import lru_cache

from pydantic import SecretStr, field_validator
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

    @field_validator("database_url", mode="before")
    @classmethod
    def blank_database_url_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings instance."""
    return Settings()
