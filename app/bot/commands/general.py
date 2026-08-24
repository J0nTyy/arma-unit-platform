"""General-purpose commands: /ping, /about, /status."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app import __version__
from app.bot.permissions import PermissionLevel, command_permission_level, require

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

_GREEN = discord.Colour.from_str("#43b581")
_ORANGE = discord.Colour.from_str("#faa61a")


class GeneralCog(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot

    def _latency_ms(self) -> str:
        latency = self.bot.latency
        if math.isnan(latency):  # not yet measured (before first heartbeat)
            return "n/a"
        return f"{round(latency * 1000)} ms"

    @app_commands.command(description="Check that the bot is responsive")
    @require(PermissionLevel.PUBLIC)
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"🟢 Pong!\nLatency: {self._latency_ms()}")

    @app_commands.command(description="What this bot is and does")
    @require(PermissionLevel.PUBLIC)
    async def about(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Arma Unit Bot",
            description=(
                "Unit management platform for an Arma 3 community.\n\n"
                "Currently in **Phase 1 (Foundation)**: core infrastructure, "
                "health monitoring and per-server configuration. Missions, "
                "signups, attendance and more arrive in later phases."
            ),
            colour=_GREEN,
        )
        embed.add_field(name="Version", value=__version__)
        embed.add_field(name="Environment", value=self.bot.settings.environment)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="List every command and what it does")
    @require(PermissionLevel.PUBLIC)
    async def help(self, interaction: discord.Interaction) -> None:
        def describe(command: app_commands.Command, qualified: str) -> str:
            level = command_permission_level(command)
            tag = f" · 🔒 {level.name.lower()}" if level >= PermissionLevel.STAFF else ""
            return f"`/{qualified}` — {command.description}{tag}"

        simple: list[str] = []
        groups: list[app_commands.Group] = []
        for top in self.bot.tree.get_commands():
            if isinstance(top, app_commands.Group):
                groups.append(top)
            elif isinstance(top, app_commands.Command):
                simple.append(describe(top, top.name))

        embed = discord.Embed(
            title="Command overview",
            description="\n".join(sorted(simple)),
            colour=discord.Colour.blurple(),
        )
        for group in sorted(groups, key=lambda g: g.name):
            lines = [
                describe(sub, f"{group.name} {sub.name}")
                for sub in sorted(group.commands, key=lambda c: c.name)
                if isinstance(sub, app_commands.Command)
            ]
            embed.add_field(
                name=f"/{group.name} — {group.description}",
                value="\n".join(lines)[:1024],
                inline=False,
            )
        embed.set_footer(text="🔒 = staff/admin only · mission IDs autocomplete as you type")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Bot, Discord and database health")
    @require(PermissionLevel.PUBLIC)
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        report = await self.bot.status_service.check()

        database_value = "🟢 Connected" if report.database_connected else "🔴 Unreachable"
        embed = discord.Embed(
            title="System Status",
            colour=_GREEN if report.database_connected else _ORANGE,
        )
        embed.add_field(name="Bot", value="🟢 Online")
        embed.add_field(name="Discord", value=f"🟢 Connected ({self._latency_ms()})")
        embed.add_field(name="Database", value=database_value)
        embed.add_field(name="Environment", value=report.environment)
        embed.add_field(name="Version", value=report.version)
        await interaction.followup.send(embed=embed)


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(GeneralCog(bot))
