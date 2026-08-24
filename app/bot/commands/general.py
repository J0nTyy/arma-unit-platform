"""General commands: /ping, /about, /help, /profile."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app import __version__
from app.bot import embeds
from app.bot.permissions import PermissionLevel, member_level, require

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

# /help is curated (not a raw command dump): sections appear only for people
# who can actually use them, and wording targets players, not developers.
_HELP_MEMBER = (
    (
        "🪖 Missions",
        "`/missions` — browse the unit's missions (filter or search)\n"
        "`/mission view` — one mission in detail, with **Brief** and "
        "**Objectives** buttons",
    ),
    (
        "🎯 Operations",
        "`/operations` — upcoming operations, pick one to view\n"
        "`/operation view` — one operation with attendance buttons\n"
        "Use 🟢 **Attend** / 🟡 **Maybe** / 🔴 **Can't Attend** on any "
        "operation post — you can change your answer any time",
    ),
    (
        "🤖 Unit assistant",
        "`/ask <question>` — ask about the unit, lore, missions, operations, "
        "rules or getting started\n"
        "You can also @mention the bot in the ask channel",
    ),
    (
        "👤 You",
        "`/profile` — your upcoming operations and attendance record",
    ),
)
_HELP_MAKER = (
    "🛠️ Mission makers",
    "`/mission publish` — post a mission to the missions channel\n"
    "`/operation create` — schedule a mission as an operation\n"
    "**Validate** and **Publish** buttons live on `/mission view`",
)
_HELP_STAFF = (
    "🛡️ Staff",
    "`/operation manage` — lock, reschedule, complete or cancel an operation\n"
    "`/unit sync` — refresh missions from GitHub\n"
    "`/unit diagnostics` — bot / database / repository health",
)
_HELP_ADMIN = (
    "⚙️ Administrators",
    "`/unit setup` — channels, roles, timezone, reminders (start here!)",
)


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
                "Unit management for an Arma 3 community: missions, operations, "
                "signups and attendance — all inside Discord.\n\n"
                "Start with `/help`."
            ),
            colour=embeds.GREEN,
        )
        embed.add_field(name="Version", value=__version__)
        embed.add_field(name="Environment", value=self.bot.settings.environment)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="What can this bot do for you?")
    @require(PermissionLevel.PUBLIC)
    async def help(self, interaction: discord.Interaction) -> None:
        level = await member_level(self.bot, interaction.user)
        embed = discord.Embed(
            title="❓ Command overview",
            description="Most things are done with **buttons** on posts — "
            "commands just get you there.",
            colour=embeds.BLURPLE,
        )
        for name, value in _HELP_MEMBER:
            embed.add_field(name=name, value=value, inline=False)
        if level >= PermissionLevel.MISSION_MAKER:
            embed.add_field(name=_HELP_MAKER[0], value=_HELP_MAKER[1], inline=False)
        if level >= PermissionLevel.STAFF:
            embed.add_field(name=_HELP_STAFF[0], value=_HELP_STAFF[1], inline=False)
        if level >= PermissionLevel.ADMIN:
            embed.add_field(name=_HELP_ADMIN[0], value=_HELP_ADMIN[1], inline=False)
        embed.set_footer(text="Need more help? Ask unit staff.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Your upcoming operations and attendance record")
    @require(PermissionLevel.MEMBER)
    async def profile(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None
        summary = await self.bot.operation_service.user_profile(
            interaction.guild.id, interaction.user.id
        )
        embed = discord.Embed(
            title=f"👤 {interaction.user.display_name}",
            colour=embeds.BLURPLE,
        )
        if summary.upcoming:
            status_icon = {"attending": "🟢", "maybe": "🟡", "waitlist": "⏳"}
            lines = [
                f"{status_icon.get(attendance.status, '•')} **{operation.name}** — "
                f"<t:{embeds.unix_ts(operation.scheduled_at)}:F>"
                for attendance, operation in summary.upcoming[:10]
            ]
            embed.add_field(name="Upcoming operations", value="\n".join(lines), inline=False)
        else:
            embed.add_field(
                name="Upcoming operations",
                value="None yet — check `/operations` and hit 🟢 **Attend**!",
                inline=False,
            )
        embed.add_field(name="Operations attended", value=str(summary.attended_count))
        embed.add_field(name="Operations responded to", value=str(summary.responded_count))
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(GeneralCog(bot))
