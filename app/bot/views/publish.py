"""Guided mission publishing: select mission → preview → channel → publish.

Duplicate-aware: if the mission is already published in this guild, the
maker is offered Update Existing / Publish Another / Cancel instead of the
bot silently creating a second post.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from app.bot import embeds
from app.bot.views.components import mission_post_view, respond_error
from app.database.models.mission import MissionIndexEntry
from app.errors import AppError, MissionNotFoundError, MissionsNotConfiguredError

if TYPE_CHECKING:
    from app.bot.bot import UnitBot
    from app.database.models.operation import MissionPublication

log = logging.getLogger(__name__)


async def _build_mission_embed(bot: "UnitBot", entry: MissionIndexEntry) -> discord.Embed:
    objectives = None
    try:
        objectives = await bot.mission_service.get_objectives(entry.mission_id)  # type: ignore[union-attr]
    except AppError:
        pass  # publish still works without the objectives block
    return embeds.mission_embed(entry, objectives)


async def continue_publish_flow(interaction: discord.Interaction, mission_id: str) -> None:
    """Entry point after permission checks; interaction must be deferred
    ephemeral (or this sends the first response)."""
    bot: "UnitBot" = interaction.client  # type: ignore[assignment]
    if bot.mission_service is None or bot.publication_service is None:
        raise MissionsNotConfiguredError()
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)

    entry = await bot.mission_service.get_mission(mission_id)
    if entry is None:
        raise MissionNotFoundError(mission_id)

    assert interaction.guild is not None
    existing = await bot.publication_service.get_publication(
        interaction.guild.id, entry.mission_id
    )
    if existing is not None:
        await interaction.followup.send(
            f"ℹ️ **{entry.mission_id} — {entry.name}** is already published in "
            f"<#{existing.channel_id}>.",
            view=DuplicatePublicationView(bot, entry, existing),
            ephemeral=True,
        )
        return
    await _send_preview(interaction, bot, entry)


async def _send_preview(
    interaction: discord.Interaction, bot: "UnitBot", entry: MissionIndexEntry
) -> None:
    configuration = await bot.guild_service.get_configuration(interaction.guild.id)  # type: ignore[union-attr]
    default_channel_id = configuration.missions_channel_id if configuration else None
    embed = await _build_mission_embed(bot, entry)
    view = PublishPreviewView(bot, entry, default_channel_id)
    hint = (
        f"Preview — publishing to <#{default_channel_id}> (change below if needed):"
        if default_channel_id
        else "Preview — **no missions channel is configured** (`/unit setup`); pick a channel below:"
    )
    await interaction.followup.send(hint, embed=embed, view=view, ephemeral=True)


class PublishPreviewView(discord.ui.View):
    def __init__(
        self, bot: "UnitBot", entry: MissionIndexEntry, default_channel_id: int | None
    ) -> None:
        super().__init__(timeout=600)
        self._bot = bot
        self._entry = entry
        self._channel_id = default_channel_id
        self._channel_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text],
            placeholder="Publish to…",
            default_values=[discord.Object(id=default_channel_id)] if default_channel_id else [],
        )
        self._channel_select.callback = self._on_channel  # type: ignore[method-assign]
        self.add_item(self._channel_select)

    async def _on_channel(self, interaction: discord.Interaction) -> None:
        self._channel_id = self._channel_select.values[0].id
        await interaction.response.defer()

    @discord.ui.button(label="Publish", emoji="📣", style=discord.ButtonStyle.success, row=1)
    async def publish(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            if self._channel_id is None:
                await interaction.followup.send(
                    "⚠️ Pick a channel first (or set one in `/unit setup`).", ephemeral=True
                )
                return
            channel = self._bot.get_channel(self._channel_id) or await self._bot.fetch_channel(
                self._channel_id
            )
            embed = await _build_mission_embed(self._bot, self._entry)
            try:
                message = await channel.send(  # type: ignore[union-attr]
                    embed=embed, view=mission_post_view(self._entry.mission_id)
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    f"⚠️ I can't post in <#{self._channel_id}> — give me View Channel and "
                    "Send Messages permission there, or pick another channel.",
                    ephemeral=True,
                )
                return
            await self._bot.publication_service.record_publication(  # type: ignore[union-attr]
                guild_id=interaction.guild.id,  # type: ignore[union-attr]
                mission_id=self._entry.mission_id,
                channel_id=message.channel.id,
                message_id=message.id,
                published_by=interaction.user.id,
            )
            self.stop()
            await interaction.followup.send(
                f"📣 Published **{self._entry.mission_id} — {self._entry.name}**: {message.jump_url}",
                ephemeral=True,
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Publishing cancelled.", view=None)


class DuplicatePublicationView(discord.ui.View):
    def __init__(
        self, bot: "UnitBot", entry: MissionIndexEntry, existing: "MissionPublication"
    ) -> None:
        super().__init__(timeout=600)
        self._bot = bot
        self._entry = entry
        self._existing = existing

    @discord.ui.button(label="Update Existing", emoji="♻️", style=discord.ButtonStyle.success)
    async def update_existing(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            updated = await refresh_single_publication(self._bot, self._existing, self._entry)
            self.stop()
            if updated:
                await interaction.followup.send(
                    f"♻️ Updated the published post for **{self._entry.mission_id}**.",
                    ephemeral=True,
                )
            else:
                await self._bot.publication_service.forget_publication(self._existing.id)  # type: ignore[union-attr]
                await interaction.followup.send(
                    "⚠️ The old post no longer exists — publishing fresh instead:",
                    ephemeral=True,
                )
                await _send_preview(interaction, self._bot, self._entry)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    @discord.ui.button(label="Publish Another", emoji="📣", style=discord.ButtonStyle.secondary)
    async def publish_another(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            self.stop()
            await _send_preview(interaction, self._bot, self._entry)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Publishing cancelled.", view=None)


async def refresh_single_publication(
    bot: "UnitBot", publication: "MissionPublication", entry: MissionIndexEntry
) -> bool:
    """Re-render one published mission post. False if the message is gone."""
    try:
        channel = bot.get_channel(publication.channel_id) or await bot.fetch_channel(
            publication.channel_id
        )
        message = channel.get_partial_message(publication.message_id)  # type: ignore[union-attr]
        embed = await _build_mission_embed(bot, entry)
        await message.edit(embed=embed, view=mission_post_view(entry.mission_id))
        return True
    except (discord.NotFound, discord.Forbidden):
        return False


async def refresh_guild_publications(bot: "UnitBot", guild_id: int) -> tuple[int, int]:
    """After /unit sync: update every published mission post (status changes
    etc.). Returns (updated, stale-forgotten)."""
    if bot.publication_service is None or bot.mission_service is None:
        return (0, 0)
    updated = stale = 0
    for publication in await bot.publication_service.list_publications(guild_id):
        entry = await bot.mission_service.get_mission(publication.mission_id)
        if entry is None:
            continue  # mission left the repo; leave the post alone for now
        if await refresh_single_publication(bot, publication, entry):
            updated += 1
        else:
            await bot.publication_service.forget_publication(publication.id)
            stale += 1
    return (updated, stale)
