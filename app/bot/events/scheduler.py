"""Background scheduler: reminders and automatic operation transitions.

Runs once a minute. All due/sent state lives in the database (per-operation
sent-at timestamps), so restarts never lose or duplicate reminders — the
loop simply asks the service "what is due now?" and delivers it.
"""

from __future__ import annotations

import logging
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


class SchedulerEvents(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot

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
