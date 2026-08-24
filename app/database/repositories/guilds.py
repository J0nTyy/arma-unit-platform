"""Data access for guild configurations.

Repositories contain query logic only — no transaction management and no
business rules. Callers (services) own the session and its transaction.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.guild import GuildConfiguration


class GuildConfigurationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_guild_id(self, guild_id: int) -> GuildConfiguration | None:
        result = await self._session.execute(
            select(GuildConfiguration).where(GuildConfiguration.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    async def upsert(self, guild_id: int, guild_name: str) -> GuildConfiguration:
        configuration = await self.get_by_guild_id(guild_id)
        if configuration is None:
            configuration = GuildConfiguration(guild_id=guild_id, guild_name=guild_name)
            self._session.add(configuration)
        else:
            configuration.guild_name = guild_name
        await self._session.flush()
        # Load server-generated timestamps so callers can read them after commit
        await self._session.refresh(configuration)
        return configuration
