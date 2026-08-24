"""Connection lifecycle events, guild registration, and member greetings."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from app.errors import DatabaseError

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)

_GREETING_FILE = "content/greeting.md"
_GREETING_FALLBACK = (
    "👋 Welcome to **{unit_name}**, {member}!\n\n{channels}\n\n"
    "Run `/help` to see what I can do, and `/profile` to set up your profile. o7"
)

# (config attribute, emoji, what it's for) — only configured ones are shown.
_GREETING_CHANNELS = (
    ("recruitment_channel_id", "📝", "new player info starts here"),
    ("briefing_channel_id", "📖", "operation briefings"),
    ("attendance_channel_id", "🪖", "sign up for operations"),
    ("ask_channel_id", "🤖", "ask me anything"),
)


def _load_greeting_template() -> str:
    """Staff-editable greeting (content/greeting.md, private/gitignored);
    falls back to the shipped example, then a built-in.

    Placeholders: {member} {unit_name} {channels}
    """
    for candidate in (_GREETING_FILE, _GREETING_FILE.replace(".md", ".example.md")):
        try:
            text = Path(candidate).read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError:
            continue
    return _GREETING_FALLBACK


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
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        try:
            await self.bot.player_service.get_or_create(
                member.guild.id, member.id, member.display_name,
                joined_at=member.joined_at,
            )
            log.info("Created/refreshed profile for joining member %s", member.id)
        except Exception:  # noqa: BLE001 — event handlers must not raise
            log.exception("Could not create profile for joining member %s", member.id)
        try:
            await self._greet(member)
        except Exception:  # noqa: BLE001
            log.exception("Could not greet joining member %s", member.id)

    async def _greet(self, member: discord.Member) -> None:
        """Post the welcome message in recruitment (fallback: general/system)."""
        configuration = await self.bot.guild_service.get_configuration(member.guild.id)
        if configuration is None:
            return
        channel = None
        for channel_id in (
            configuration.recruitment_channel_id,
            configuration.general_channel_id,
            member.guild.system_channel.id if member.guild.system_channel else None,
        ):
            if channel_id and (candidate := member.guild.get_channel(channel_id)):
                channel = candidate
                break
        if channel is None:
            return  # no greeting channel configured — greetings are off

        channel_lines = [
            f"{emoji} <#{getattr(configuration, key)}> — {purpose}"
            for key, emoji, purpose in _GREETING_CHANNELS
            if getattr(configuration, key)
        ]
        text = _load_greeting_template().format(
            member=member.mention,
            unit_name=configuration.unit_name or member.guild.name,
            channels="\n".join(channel_lines) or "Take a look around the channels!",
        )
        try:
            await channel.send(
                text[:1990],
                allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False),
            )
            log.info("Greeted new member %s in #%s", member.id, channel.name)
        except discord.Forbidden:
            log.warning("No permission to greet in #%s", channel.name)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return
        try:
            # History is preserved — the profile is only stamped as departed.
            await self.bot.player_service.mark_left(member.guild.id, member.id)
            log.info("Marked member %s as departed (records preserved)", member.id)
        except Exception:  # noqa: BLE001
            log.exception("Could not mark member %s as departed", member.id)

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
