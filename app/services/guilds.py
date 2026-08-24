"""Guild configuration business logic.

Services own transactions and translate infrastructure failures into
application errors. Interfaces (Discord commands, API routes) call services
and never touch sessions or SQLAlchemy directly.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError

from app.database import Database
from app.database.models.guild import GuildConfiguration
from app.database.repositories.guilds import GuildConfigurationRepository
from app.errors import DatabaseError

log = logging.getLogger(__name__)


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
