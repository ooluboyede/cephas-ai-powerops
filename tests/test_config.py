from powerops.config import Settings


def test_settings_have_safe_development_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_name == "CEPHAS AI PowerOps"
    assert settings.app_env == "development"
    assert settings.log_level == "INFO"


def test_settings_accept_explicit_deployment_values() -> None:
    settings = Settings(
        _env_file=None,
        app_name="PowerOps test",
        app_env="test",
        log_level="WARNING",
    )
    assert settings.app_name == "PowerOps test"
    assert settings.app_env == "test"
    assert settings.log_level == "WARNING"
