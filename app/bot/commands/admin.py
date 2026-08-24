"""Administrator-only configuration commands.

Two layers of protection:
- ``default_permissions`` hides the commands from non-admins in the Discord UI
  (cosmetic — server owners can override it).
- ``@require(PermissionLevel.ADMIN)`` enforces the permission server-side on
  every invocation. This is the layer that actually matters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.permissions import PermissionLevel, require

if TYPE_CHECKING:
    from app.bot.bot import UnitBot


class AdminCog(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot

    config = app_commands.Group(
        name="config",
        description="Server configuration (administrators only)",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    @config.command(name="setup", description="Register or refresh this server's configuration")
    @require(PermissionLevel.ADMIN)
    async def config_setup(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None  # guaranteed by guild_only
        configuration = await self.bot.guild_service.register_guild(
            interaction.guild.id, interaction.guild.name
        )
        embed = discord.Embed(
            title="Server registered",
            description=f"**{configuration.guild_name}** is now configured.",
            colour=discord.Colour.from_str("#43b581"),
        )
        embed.add_field(name="Guild ID", value=str(configuration.guild_id))
        embed.add_field(name="First configured", value=f"{configuration.configured_at:%Y-%m-%d %H:%M} UTC")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config.command(name="view", description="Show this server's stored configuration")
    @require(PermissionLevel.ADMIN)
    async def config_view(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        configuration = await self.bot.guild_service.get_configuration(interaction.guild.id)
        if configuration is None:
            await interaction.response.send_message(
                "⚠️ This server is not configured yet. Run `/config setup` first.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(title="Server configuration", colour=discord.Colour.blurple())
        embed.add_field(name="Guild ID", value=str(configuration.guild_id))
        embed.add_field(name="Name", value=configuration.guild_name)
        embed.add_field(name="First configured", value=f"{configuration.configured_at:%Y-%m-%d %H:%M} UTC")
        embed.add_field(name="Last updated", value=f"{configuration.updated_at:%Y-%m-%d %H:%M} UTC")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(AdminCog(bot))
