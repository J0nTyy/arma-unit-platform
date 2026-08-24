"""Connection lifecycle events and automatic guild registration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from app.errors import DatabaseError

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)


class LifecycleEvents(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        log.info(
            "Connected to Discord as %s (id=%s) — serving %d guild(s)",
            self.bot.user, self.bot.user.id if self.bot.user else "?", len(self.bot.guilds),
        )

    @commands.Cog.listener()
    async def on_resumed(self) -> None:
        log.info("Discord session resumed")

    @commands.Cog.listener()
    async def on_disconnect(self) -> None:
        # Fires on routine reconnects too, so keep it quiet.
        log.debug("Disconnected from Discord gateway")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        log.info("Joined guild %s (id=%s)", guild.name, guild.id)
        try:
            await self.bot.guild_service.register_guild(guild.id, guild.name)
        except DatabaseError:
            log.error("Could not auto-register guild %s; run /config setup later", guild.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        log.info("Removed from guild %s (id=%s)", guild.name, guild.id)


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(LifecycleEvents(bot))
