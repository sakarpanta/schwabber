import pytest

from schwabber.config import ConfigurationError, Settings


def test_settings_require_a_long_middleware_key() -> None:
    with pytest.raises(ConfigurationError, match="at least 32"):
        Settings.from_mapping({"SCHWABBER_API_KEY": "short"})


def test_missing_schwab_values_create_degraded_configuration() -> None:
    settings = Settings.from_mapping({"SCHWABBER_API_KEY": "x" * 32})
    assert settings.schwab_configured is False
    assert settings.token_path.as_posix() == "/data/token.json"


def test_sec_is_configured_with_contact_identity() -> None:
    settings = Settings.from_mapping(
        {"SCHWABBER_API_KEY": "x" * 32, "SEC_USER_AGENT": "App me@example.com"}
    )
    assert settings.sec_configured is True
