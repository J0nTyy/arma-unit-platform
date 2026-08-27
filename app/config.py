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

# AI provider -> (default model, base URL override, settings key field)
# gemini-flash-latest is an alias that always tracks Google's current flash
# model — pinned versions age out of the API (and their free-tier quotas vary
# wildly: new flagship models may allow only ~20 free requests/day).
# claude uses the official Anthropic SDK (not the OpenAI-compatible path);
# claude-opus-4-8 is Anthropic's flagship — pin AI_MODEL=claude-haiku-4-5
# for a much cheaper option.
AI_PROVIDER_DEFAULTS = {
    "openai": ("gpt-5-mini", None, "openai_api_key"),
    "gemini": (
        "gemini-flash-latest",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini_api_key",
    ),
    "claude": ("claude-opus-4-8", None, "anthropic_api_key"),
}


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

    # AI assistant. openai/gemini share one OpenAI-compatible client; claude
    # uses the official Anthropic SDK. Switch with AI_PROVIDER, no code changes.
    ai_provider: Literal["openai", "gemini", "claude"] = "openai"
    ai_model: str | None = None  # blank = the provider's default below
    ai_base_url: str | None = None  # override for other compatible providers
    # Reasoning models (gpt-5 family) spend hidden "thinking" tokens that cost
    # credits; "low" keeps answers good while cutting that spend. Blank = "low"
    # on openai, unset elsewhere.
    ai_reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None
    ai_max_output_tokens: int = 700
    ai_requests_per_minute: int = 4
    ai_personality_file: str = "unit/personality/personality.md"
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    @property
    def resolved_ai_model(self) -> str:
        return self.ai_model or AI_PROVIDER_DEFAULTS[self.ai_provider][0]

    @property
    def resolved_ai_base_url(self) -> str | None:
        return self.ai_base_url or AI_PROVIDER_DEFAULTS[self.ai_provider][1]

    @property
    def resolved_ai_key(self) -> SecretStr | None:
        return getattr(self, AI_PROVIDER_DEFAULTS[self.ai_provider][2])

    @property
    def resolved_ai_reasoning_effort(self) -> str | None:
        if self.ai_reasoning_effort:
            return self.ai_reasoning_effort
        return "low" if self.ai_provider == "openai" else None

    @property
    def ai_configured(self) -> bool:
        return self.resolved_ai_key is not None

    @property
    def missions_repository_configured(self) -> bool:
        return bool(self.github_missions_owner and self.github_missions_repository)

    @field_validator(
        "dev_guild_ids",
        "github_token",
        "github_missions_owner",
        "github_missions_repository",
        "openai_api_key",
        "gemini_api_key",
        "anthropic_api_key",
        "ai_model",
        "ai_base_url",
        "ai_reasoning_effort",
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
