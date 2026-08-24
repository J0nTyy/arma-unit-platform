"""Application configuration.

All configuration comes from environment variables, optionally loaded from a
local `.env` file. Required values fail fast at startup with a clear error
message instead of crashing later with a cryptic one.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.errors import ConfigurationError

_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


def normalize_database_url(url: str) -> str:
    """Map plain database URLs onto the async drivers this application uses.

    ``postgresql://...`` -> ``postgresql+asyncpg://...``
    ``sqlite://...``     -> ``sqlite+aiosqlite://...``
    URLs that already name an async driver pass through unchanged.
    """
    if url.startswith("postgres://"):  # legacy Heroku-style scheme
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if url.startswith("sqlite://"):
        return "sqlite+aiosqlite://" + url.removeprefix("sqlite://")
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Discord (required)
    discord_token: SecretStr
    discord_application_id: int
    # Guilds that get instant command sync (optional, comma-separated IDs).
    # Leave empty to sync commands globally instead (production mode).
    dev_guild_ids: str | None = None

    # Database (required)
    database_url: str

    # Application
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    # HTTP API
    api_enabled: bool = True
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # GitHub mission repository (optional — /mission commands explain setup
    # when unconfigured). Token is optional for public repositories.
    github_token: SecretStr | None = None
    github_missions_owner: str | None = None
    github_missions_repository: str | None = None
    github_missions_branch: str = "main"

    # Reserved for future phases — validated but unused today.
    openai_api_key: SecretStr | None = None

    @property
    def missions_repository_configured(self) -> bool:
        return bool(self.github_missions_owner and self.github_missions_repository)

    @field_validator(
        "dev_guild_ids",
        "github_token",
        "github_missions_owner",
        "github_missions_repository",
        "openai_api_key",
        mode="before",
    )
    @classmethod
    def _empty_string_is_none(cls, value: object) -> object:
        """Treat blank values from `.env` templates as unset."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("dev_guild_ids")
    @classmethod
    def _validate_dev_guild_ids(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ids = [int(part) for part in value.split(",") if part.strip()]
        except ValueError:
            raise ValueError(
                "DEV_GUILD_IDS must be comma-separated Discord server IDs, e.g. '123,456'"
            )
        return ",".join(str(guild_id) for guild_id in ids) or None

    @property
    def dev_guild_id_list(self) -> tuple[int, ...]:
        """DEV_GUILD_IDS parsed into integers; empty when unset."""
        if not self.dev_guild_ids:
            return ()
        return tuple(int(part) for part in self.dev_guild_ids.split(","))

    @field_validator("discord_token")
    @classmethod
    def _token_not_blank(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("DISCORD_TOKEN must not be empty")
        return value

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("DATABASE_URL must not be empty")
        return normalize_database_url(value.strip())

    @field_validator("github_missions_branch", mode="before")
    @classmethod
    def _blank_branch_means_main(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return "main"
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(_LOG_LEVELS)}")
        return level


def load_settings(env_file: str | None = ".env") -> Settings:
    """Build settings, translating pydantic errors into a readable message."""
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']).upper()}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigurationError(
            f"Invalid or missing configuration: {problems}. "
            "Copy .env.example to .env and fill in the required values."
        ) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


class _DatabaseOnlySettings(BaseSettings):
    """Minimal settings used by Alembic, which only needs the database URL.

    Deliberately separate from `Settings` so running migrations does not
    require a Discord token to be configured.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str

    @field_validator("database_url")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_database_url(value.strip())


def get_database_url() -> str:
    try:
        return _DatabaseOnlySettings().database_url
    except ValidationError as exc:
        raise ConfigurationError(
            "DATABASE_URL is not configured. Set it in the environment or in .env."
        ) from exc
