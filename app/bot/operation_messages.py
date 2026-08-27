"""Operation message workflows: briefing posts, announcements, archiving.

Layout per operation:
- #operation-brief : the formatted briefing as plain messages + mission images
- #attendance      : the signup post (embed + attendance buttons)
- announcements    : @everyone notice on publish / cancel / reschedule,
                     mirrored to the configured general channel
- #operation-logs  : staff archive — completed ops move here immediately,
                     cancelled ones after 24 hours
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

import discord

from app.bot import embeds
from app.database.models.guild import GuildConfiguration
from app.database.models.operation import Operation
from app.errors import AppError

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)

_EVERYONE = discord.AllowedMentions(everyone=True, users=True, roles=False)


async def _get_channel(bot: "UnitBot", channel_id: int | None):
    if channel_id is None:
        return None
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden):
            return None
    return channel


async def post_briefing(
    bot: "UnitBot", channel: discord.abc.Messageable, operation: Operation
) -> list[int]:
    """Post the formatted briefing + mission images; returns the message IDs."""
    message_ids: list[int] = []
    chunks: list[str] = []
    if bot.mission_service is not None:
        try:
            content = await bot.mission_service.get_brief(operation.mission_id)
            chunks = embeds.brief_message_chunks(operation.name, content)
        except AppError:
            log.warning("Briefing unavailable for %s", operation.mission_id)
    files: list[discord.File] = []
    if bot.mission_service is not None:
        try:
            files = [
                discord.File(io.BytesIO(data), filename=filename)
                for filename, data in await bot.mission_service.get_attachments(
                    operation.mission_id
                )
            ]
        except AppError:
            log.warning("Attachments unavailable for %s", operation.mission_id)

    for chunk in chunks:
        message = await channel.send(chunk, allowed_mentions=discord.AllowedMentions.none())
        message_ids.append(message.id)
    if files:  # images appear under the briefing text
        message = await channel.send(files=files)
        message_ids.append(message.id)
    return message_ids


async def announce_operation(bot: "UnitBot", operation: Operation, event: str) -> None:
    """@everyone notice in the announcements channel, mirrored to general."""
    configuration = await bot.guild_service.get_configuration(operation.guild_id)
    if configuration is None:
        return
    unix = embeds.unix_ts(operation.scheduled_at)
    jump = (
        f"https://discord.com/channels/{operation.guild_id}/"
        f"{operation.channel_id}/{operation.message_id}"
        if operation.channel_id and operation.message_id
        else ""
    )
    # The factual line is fixed; a varied flavor line closes the message
    # (witty variants only when the unit's humour setting allows).
    texts = {
        "published": (
            f"📣 @everyone **New operation: {operation.name}** — <t:{unix}:F> (<t:{unix}:R>)\n"
            f"Read the briefing and sign up here: {jump}"
        ),
        "cancelled": (
            f"🔴 @everyone **Operation {operation.name}** (<t:{unix}:F>) has been **cancelled**."
        ),
        "rescheduled": (
            f"🟡 @everyone **Operation {operation.name}** has been **rescheduled** to "
            f"<t:{unix}:F> (<t:{unix}:R>).\nUpdate your attendance: {jump}"
        ),
    }
    text = texts[event]
    tail = bot.messages.pick(f"announce_{event}_tail", fallback="")
    if tail:
        text = f"{text}\n{tail}"

    guild = bot.get_guild(operation.guild_id)
    general_id = configuration.general_channel_id
    if general_id is None and guild is not None and guild.system_channel is not None:
        general_id = guild.system_channel.id

    channel_ids = {configuration.announcements_channel_id, general_id}
    channel_ids.discard(None)
    if not channel_ids:
        log.info("No announcement channels configured for guild %s", operation.guild_id)
        return
    for channel_id in channel_ids:
        channel = await _get_channel(bot, channel_id)
        if channel is None:
            continue
        try:
            await channel.send(text, allowed_mentions=_EVERYONE)
        except discord.HTTPException:
            log.exception("Could not announce in channel %s", channel_id)


async def archive_operation(bot: "UnitBot", operation: Operation) -> bool:
    """Move a finished/cancelled operation to the staff logs channel.

    Reposts the final state (attendance board + briefing) to the configured
    operation-logs channel, then deletes the originals so the attendance and
    briefing channels stay clean. Returns True when done.
    """
    configuration = await bot.guild_service.get_configuration(operation.guild_id)
    logs_channel = await _get_channel(
        bot, configuration.operation_logs_channel_id if configuration else None
    )
    if logs_channel is None:
        log.info(
            "No operation-logs channel for guild %s — leaving operation %d in place",
            operation.guild_id, operation.id,
        )
        return False

    mission = None
    if bot.mission_service is not None:
        mission = await bot.mission_service.get_mission(operation.mission_id)
    roster = await bot.operation_service.roster(operation.id)
    badge = embeds.OPERATION_STATUS_BADGE.get(operation.status, operation.status)

    try:
        await logs_channel.send(
            f"📦 **Operation log — {operation.name}** · {badge}",
            embed=embeds.operation_embed(operation, mission, roster),
        )
        for chunk_ids, channel_id in (
            (operation.brief_message_ids or [], operation.brief_channel_id),
            ([operation.message_id] if operation.message_id else [], operation.channel_id),
        ):
            channel = await _get_channel(bot, channel_id)
            if channel is None:
                continue
            for message_id in chunk_ids:
                try:
                    await channel.get_partial_message(message_id).delete()
                except (discord.NotFound, discord.Forbidden):
                    pass
    except discord.HTTPException:
        log.exception("Archiving operation %d failed; will retry next tick", operation.id)
        return False
    log.info("Archived operation %d (%s) to logs", operation.id, operation.name)
    return True


def _channels_ready(configuration: GuildConfiguration | None) -> list[str]:
    """Names of the channels still missing for the publish flow."""
    missing = []
    if configuration is None or configuration.attendance_channel_id is None:
        missing.append("Attendance")
    if configuration is None or configuration.briefing_channel_id is None:
        missing.append("Operation brief")
    return missing
