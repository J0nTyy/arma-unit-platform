"""Background scheduler: reminders, operation transitions, post archiving,
and ambient chatter.

Runs once a minute. Reminder/archive state lives in the database so restarts
never lose or duplicate work. Chatter timing is in-memory on purpose — a
restart just re-rolls the next random interval.
"""

from __future__ import annotations

import logging
import random
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from app.bot.operation_messages import archive_operation
from app.bot.views.components import refresh_operation_message
from app.services.operations import DueReminder

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)

_MAX_MENTIONS = 40
# Ambient chatter fires at a random interval in this window (per guild).
_CHATTER_MIN_SECONDS = 5 * 60
_CHATTER_MAX_SECONDS = 30 * 60
_CHATTER_MIN_HUMAN_MESSAGES = 5  # stay quiet in quiet channels


class SchedulerEvents(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot
        self._next_chatter: dict[int, float] = {}  # guild_id -> monotonic deadline
        self._next_sheets: dict[int, float] = {}   # guild_id -> monotonic deadline

    async def cog_load(self) -> None:
        self.tick.start()

    async def cog_unload(self) -> None:
        self.tick.cancel()

    @tasks.loop(seconds=60)
    async def tick(self) -> None:
        try:
            result = await self.bot.operation_service.tick()
        except Exception:  # noqa: BLE001 — the loop must survive bad passes
            log.exception("Scheduler tick failed")
            return
        for operation in result.activated:
            log.info("Operation %d (%s) is now active", operation.id, operation.name)
            await refresh_operation_message(self.bot, operation)
        for reminder in result.reminders:
            await self._deliver(reminder)
        for operation in result.to_archive:
            if await archive_operation(self.bot, operation):
                await self.bot.operation_service.mark_archived(operation.id)
        try:
            await self._chatter_pass()
        except Exception:  # noqa: BLE001 — chatter must never break the scheduler
            log.exception("Chatter pass failed")
        try:
            await self._sheets_pass()
        except Exception:  # noqa: BLE001
            log.exception("Sheets pass failed")

    async def _chatter_pass(self) -> None:
        """Occasional in-character message in the general channel (opt-in)."""
        if self.bot.assistant_service is None:
            return
        for guild in self.bot.guilds:
            deadline = self._next_chatter.get(guild.id)
            if deadline is None:
                self._reroll_chatter(guild.id)
                continue
            if time.monotonic() < deadline:
                continue
            self._reroll_chatter(guild.id)  # roll next slot no matter what happens

            configuration = await self.bot.guild_service.get_configuration(guild.id)
            if (
                configuration is None
                or not configuration.chatter_enabled
                or configuration.general_channel_id is None
            ):
                continue
            channel = guild.get_channel(configuration.general_channel_id)
            if channel is None:
                continue
            try:
                lines: list[str] = []
                human_messages = 0
                last_was_bot = False
                async for message in channel.history(limit=25):
                    if not message.content.strip():
                        continue
                    if not lines:
                        last_was_bot = message.author == self.bot.user
                    if not message.author.bot:
                        human_messages += 1
                    author = "you" if message.author == self.bot.user else message.author.display_name
                    lines.append(f"{author}: {message.content[:150]}")
                if last_was_bot or human_messages < _CHATTER_MIN_HUMAN_MESSAGES:
                    continue  # nothing lively to react to / don't double-post
                lines.reverse()
                text = await self.bot.assistant_service.chatter(
                    "\n".join(lines)[-1500:],
                    configuration.unit_name or guild.name,
                )
                if text:
                    await channel.send(
                        text, allowed_mentions=discord.AllowedMentions.none()
                    )
                    log.info("Chatter posted in guild %s", guild.id)
            except discord.HTTPException:
                log.warning("Chatter failed for guild %s", guild.id)

    def _reroll_chatter(self, guild_id: int) -> None:
        self._next_chatter[guild_id] = time.monotonic() + random.randint(
            _CHATTER_MIN_SECONDS, _CHATTER_MAX_SECONDS
        )

    async def _sheets_pass(self) -> None:
        """Daily automatic spreadsheet refresh (first run ~10min after boot)."""
        if self.bot.sheets_service is None:
            return
        for guild in self.bot.guilds:
            deadline = self._next_sheets.get(guild.id)
            if deadline is None:
                self._next_sheets[guild.id] = time.monotonic() + 600
                continue
            if time.monotonic() < deadline:
                continue
            self._next_sheets[guild.id] = time.monotonic() + 24 * 3600
            try:
                results = await self.bot.sheets_service.export_all(guild.id)
                log.info("Daily sheets export for guild %s: %s", guild.id, results)
            except Exception:  # noqa: BLE001 — retry tomorrow
                log.exception("Daily sheets export failed for guild %s", guild.id)

    @tick.before_loop
    async def before_tick(self) -> None:
        await self.bot.wait_until_ready()

    async def _deliver(self, reminder: DueReminder) -> None:
        operation = reminder.operation
        try:
            channel = self.bot.get_channel(operation.channel_id) or await self.bot.fetch_channel(
                operation.channel_id  # type: ignore[arg-type]
            )
        except (discord.NotFound, discord.Forbidden):
            log.warning("Reminder channel missing for operation %d", operation.id)
            return

        from app.bot.embeds import unix_ts  # local import avoids cycles at module load

        unix = unix_ts(operation.scheduled_at)
        label = "24 hours" if reminder.kind == "24h" else "1 hour"
        lines = [
            f"⏰ **{operation.name}** starts in about {label} — <t:{unix}:F> (<t:{unix}:R>)."
        ]
        if reminder.attendee_ids:
            mentions = [f"<@{uid}>" for uid in reminder.attendee_ids[:_MAX_MENTIONS]]
            extra = len(reminder.attendee_ids) - _MAX_MENTIONS
            if extra > 0:
                mentions.append(f"+{extra} more")
            lines.append("🟢 " + " ".join(mentions))
        elif reminder.kind == "24h":
            lines.append("No confirmed attendees yet — hit 🟢 **Attend** on the post above!")

        reference = None
        if operation.message_id:
            reference = discord.MessageReference(
                message_id=operation.message_id,
                channel_id=operation.channel_id,  # type: ignore[arg-type]
                fail_if_not_exists=False,
            )
        try:
            await channel.send("\n".join(lines), reference=reference)  # type: ignore[union-attr]
            log.info("Sent %s reminder for operation %d", reminder.kind, operation.id)
        except discord.HTTPException:
            log.exception("Failed to send reminder for operation %d", operation.id)


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(SchedulerEvents(bot))
