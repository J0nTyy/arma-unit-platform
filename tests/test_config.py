import pytest

from app.config import Settings, load_settings, normalize_database_url
from app.errors import ConfigurationError

ALL_ENV_VARS = [
    "DISCORD_TOKEN",
    "DISCORD_APPLICATION_ID",
    "DEV_GUILD_IDS",
    "DATABASE_URL",
    "ENVIRONMENT",
    "LOG_LEVEL",
    "API_ENABLED",
    "API_HOST",
    "API_PORT",
    "GITHUB_TOKEN",
    "OPENAI_API_KEY",
]

REQUIRED = {
    "DISCORD_TOKEN": "test-token-value",
    "DISCORD_APPLICATION_ID": "123456789012345678",
    "DATABASE_URL": "postgresql://user:pass@localhost:5432/unit",
}


@pytest.fixture
def clean_env(monkeypatch):
    """Strip all application env vars so tests are hermetic."""
    for var in ALL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_missing_required_configuration_fails_clearly(clean_env):
    with pytest.raises(ConfigurationError) as exc_info:
        load_settings(env_file=None)
    message = str(exc_info.value)
    assert "DISCORD_TOKEN" in message
    assert "DATABASE_URL" in message


def test_valid_configuration_parses(clean_env):
    for key, value in REQUIRED.items():
        clean_env.setenv(key, value)
    settings = load_settings(env_file=None)
    assert settings.discord_application_id == 123456789012345678
    assert settings.discord_token.get_secret_value() == "test-token-value"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    # Plain postgresql:// is upgraded to the async driver
    assert settings.database_url == "postgresql+asyncpg://user:pass@localhost:5432/unit"


def test_secrets_are_not_exposed_in_repr(clean_env):
    for key, value in REQUIRED.items():
        clean_env.setenv(key, value)
    settings = load_settings(env_file=None)
    assert "test-token-value" not in repr(settings)
    assert "test-token-value" not in str(settings)


def test_empty_optional_values_treated_as_unset(clean_env):
    for key, value in REQUIRED.items():
        clean_env.setenv(key, value)
    clean_env.setenv("DEV_GUILD_IDS", "")
    clean_env.setenv("GITHUB_TOKEN", "")
    settings = load_settings(env_file=None)
    assert settings.dev_guild_ids is None
    assert settings.dev_guild_id_list == ()
    assert settings.github_token is None


def test_single_dev_guild_id_parses(clean_env):
    for key, value in REQUIRED.items():
        clean_env.setenv(key, value)
    clean_env.setenv("DEV_GUILD_IDS", "123456789012345678")
    settings = load_settings(env_file=None)
    assert settings.dev_guild_id_list == (123456789012345678,)


def test_multiple_dev_guild_ids_parse(clean_env):
    for key, value in REQUIRED.items():
        clean_env.setenv(key, value)
    clean_env.setenv("DEV_GUILD_IDS", "111, 222,333")
    settings = load_settings(env_file=None)
    assert settings.dev_guild_id_list == (111, 222, 333)


def test_invalid_dev_guild_ids_rejected(clean_env):
    for key, value in REQUIRED.items():
        clean_env.setenv(key, value)
    clean_env.setenv("DEV_GUILD_IDS", "not-a-guild-id")
    with pytest.raises(ConfigurationError):
        load_settings(env_file=None)


def test_invalid_log_level_rejected(clean_env):
    for key, value in REQUIRED.items():
        clean_env.setenv(key, value)
    clean_env.setenv("LOG_LEVEL", "verbose")
    with pytest.raises(ConfigurationError):
        load_settings(env_file=None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgresql://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("postgres://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("postgresql+asyncpg://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("sqlite:///./dev.db", "sqlite+aiosqlite:///./dev.db"),
        ("sqlite+aiosqlite:///./dev.db", "sqlite+aiosqlite:///./dev.db"),
    ],
)
def test_database_url_normalization(raw, expected):
    assert normalize_database_url(raw) == expected
