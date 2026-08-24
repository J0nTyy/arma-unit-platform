"""Guild configuration business logic.

Services own transactions and translate infrastructure failures into
application errors. Interfaces (Discord commands, API routes) call services
and never touch sessions or SQLAlchemy directly.
"""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.database.models.guild import GuildConfiguration
from app.database.repositories.guilds import GuildConfigurationRepository
from app.errors import DatabaseError, ValidationError

log = logging.getLogger(__name__)

# Settings /unit setup may write. Anything else is rejected loudly.
_UPDATABLE_FIELDS = {
    "unit_name",
    "timezone",
    "reminders_enabled",
    "staff_role_id",
    "mission_maker_role_id",
    "trainer_role_id",
    "chatter_enabled",
    "operations_channel_id",
    "missions_channel_id",
    "announcements_channel_id",
    "logs_channel_id",
    "recruitment_channel_id",
    "aar_channel_id",
    "staff_channel_id",
    "attendance_channel_id",
    "briefing_channel_id",
    "operation_logs_channel_id",
    "general_channel_id",
    "ask_channel_id",
}


def validate_timezone(name: str) -> str:
    """Validate an IANA timezone name, returning its canonical spelling."""
    candidate = name.strip()
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(
            f"unknown timezone {candidate!r}",
            user_message=(
                f"`{candidate}` is not a valid timezone. Use an IANA name like "
                "`Asia/Kolkata`, `Europe/Berlin` or `America/New_York`."
            ),
        ) from exc
    return candidate


class GuildService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def register_guild(self, guild_id: int, guild_name: str) -> GuildConfiguration:
        """Create or refresh the configuration record for a guild."""
        try:
            async with self._database.session() as session:
                async with session.begin():
                    repository = GuildConfigurationRepository(session)
                    configuration = await repository.upsert(guild_id, guild_name)
            log.info("Registered guild %s (%r)", guild_id, guild_name)
            return configuration
        except SQLAlchemyError as exc:
            log.exception("Failed to register guild %s", guild_id)
            raise DatabaseError(f"register_guild({guild_id}) failed") from exc

    async def get_configuration(self, guild_id: int) -> GuildConfiguration | None:
        try:
            async with self._database.session() as session:
                repository = GuildConfigurationRepository(session)
                return await repository.get_by_guild_id(guild_id)
        except SQLAlchemyError as exc:
            log.exception("Failed to load configuration for guild %s", guild_id)
            raise DatabaseError(f"get_configuration({guild_id}) failed") from exc

    async def update_settings(
        self, guild_id: int, guild_name: str, **fields: object
    ) -> GuildConfiguration:
        """Update configuration fields, registering the guild if needed."""
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValueError(f"not updatable via update_settings: {sorted(unknown)}")
        if "timezone" in fields and fields["timezone"] is not None:
            fields["timezone"] = validate_timezone(str(fields["timezone"]))
        try:
            async with self._database.session() as session:
                async with session.begin():
                    repository = GuildConfigurationRepository(session)
                    configuration = await repository.upsert(guild_id, guild_name)
                    for key, value in fields.items():
                        setattr(configuration, key, value)
                    await session.flush()
                    await session.refresh(configuration)
            log.info("Updated settings for guild %s: %s", guild_id, sorted(fields))
            return configuration
        except SQLAlchemyError as exc:
            log.exception("Failed to update settings for guild %s", guild_id)
            raise DatabaseError(f"update_settings({guild_id}) failed") from exc
