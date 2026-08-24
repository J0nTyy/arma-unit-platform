"""Guided operation scheduling: mission → date/time modal → preview → publish.

No ten-parameter commands: the mission comes from a select menu (or the
Schedule button on a mission post), everything else from one modal, and the
result is previewed before anything goes public.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

import io

from app.bot import embeds
from app.bot.views.components import (
    group_embeds,
    operation_post_view,
    respond_error,
)
from app.database.models.mission import MissionIndexEntry
from app.errors import AppError, MissionNotFoundError, MissionsNotConfiguredError, ValidationError
from app.services.operations import Roster

if TYPE_CHECKING:
    from app.bot.bot import UnitBot
    from app.database.models.operation import Operation

log = logging.getLogger(__name__)


async def _guild_timezone(bot: "UnitBot", guild: discord.Guild) -> str:
    configuration = await bot.guild_service.get_configuration(guild.id)
    if configuration is None or not configuration.timezone:
        raise ValidationError(
            "guild timezone unset",
            user_message=(
                "The unit timezone isn't set yet. An administrator must run "
                "`/unit setup` and set **Timezone** before operations can be scheduled."
            ),
        )
    return configuration.timezone


async def start_schedule_flow(
    interaction: discord.Interaction, mission_id: str | None = None
) -> None:
    """First response to the interaction: either the details modal (mission
    known) or an ephemeral mission picker."""
    bot: "UnitBot" = interaction.client  # type: ignore[assignment]
    if bot.mission_service is None:
        raise MissionsNotConfiguredError()
    assert interaction.guild is not None
    tz_name = await _guild_timezone(bot, interaction.guild)

    if mission_id is not None:
        entry = await bot.mission_service.get_mission(mission_id)
        if entry is None:
            raise MissionNotFoundError(mission_id)
        await interaction.response.send_modal(OperationDetailsModal(bot, entry, tz_name))
        return

    entries = [
        entry
        for entry in await bot.mission_service.list_missions()
        if entry.status != "archived"
    ]
    if not entries:
        await interaction.response.send_message(
            "📭 No missions in the index. Run `/unit sync` first.", ephemeral=True
        )
        return
    await interaction.response.send_message(
        "**Create Operation** — pick the mission to schedule:",
        view=MissionPickView(bot, entries, tz_name),
        ephemeral=True,
    )


class MissionPickView(discord.ui.View):
    def __init__(
        self, bot: "UnitBot", entries: list[MissionIndexEntry], tz_name: str
    ) -> None:
        super().__init__(timeout=600)
        self._bot = bot
        self._by_id = {entry.mission_id: entry for entry in entries[:25]}
        self._tz_name = tz_name
        select = discord.ui.Select(
            placeholder="Select mission…",
            options=[
                discord.SelectOption(
                    label=f"{entry.mission_id} — {entry.name}"[:100],
                    value=entry.mission_id,
                    description=f"{entry.map_name} · {entry.mission_type} · "
                    f"~{entry.estimated_duration_minutes} min"[:100],
                )
                for entry in self._by_id.values()
            ],
        )
        select.callback = self._on_pick  # type: ignore[method-assign]
        self._select = select
        self.add_item(select)

    async def _on_pick(self, interaction: discord.Interaction) -> None:
        try:
            entry = self._by_id[self._select.values[0]]
            await interaction.response.send_modal(
                OperationDetailsModal(self._bot, entry, self._tz_name)
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class OperationDetailsModal(discord.ui.Modal):
    def __init__(self, bot: "UnitBot", entry: MissionIndexEntry, tz_name: str) -> None:
        super().__init__(title=f"Schedule {entry.mission_id}"[:45])
        self._bot = bot
        self._entry = entry
        self._tz_name = tz_name
        self.date_input = discord.ui.TextInput(
            label=f"Date (DD/MM/YYYY, {tz_name})", placeholder="05/09/2026", max_length=10
        )
        self.time_input = discord.ui.TextInput(
            label="Time (24h HH:MM)", placeholder="20:00", max_length=5
        )
        self.name_input = discord.ui.TextInput(
            label="Operation name (anything you like)", default=entry.name, max_length=100
        )
        for item in (self.date_input, self.time_input, self.name_input):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            bot = self._bot
            service = bot.operation_service
            when_utc = service.parse_local_datetime(
                self.date_input.value, self.time_input.value, self._tz_name
            )
            objectives_text = None
            try:
                objectives = await bot.mission_service.get_objectives(self._entry.mission_id)  # type: ignore[union-attr]
                objectives_text = embeds.render_objectives(objectives)
            except AppError:
                pass  # operation still schedulable without the objectives block

            operation = await service.create_operation(
                guild_id=interaction.guild.id,  # type: ignore[union-attr]
                mission_id=self._entry.mission_id,
                mission_name=self._entry.name,
                mission_status=self._entry.status,
                scheduled_at_utc=when_utc,
                tz_name=self._tz_name,
                created_by=interaction.user.id,
                name=self.name_input.value,
            )
            if objectives_text:
                operation = await service.set_objectives_snapshot(operation.id, objectives_text)

            preview = embeds.operation_embed(operation, self._entry, Roster([], [], [], []))
            configuration = await bot.guild_service.get_configuration(interaction.guild.id)  # type: ignore[union-attr]
            channel_id = configuration.operations_channel_id if configuration else None
            hint = (
                f"Preview — publish to <#{channel_id}>?"
                if channel_id
                else "Preview — ⚠️ **no operations channel configured** (`/unit setup`). "
                "Configure it, then press Publish."
            )
            await interaction.followup.send(
                hint,
                embed=preview,
                view=PublishOperationView(bot, operation.id),
                ephemeral=True,
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class PublishOperationView(discord.ui.View):
    def __init__(self, bot: "UnitBot", operation_id: int) -> None:
        super().__init__(timeout=900)
        self._bot = bot
        self._operation_id = operation_id

    @discord.ui.button(label="Publish to operations channel", emoji="📣",
                       style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            bot = self._bot
            operation = await bot.operation_service.get(self._operation_id)
            configuration = await bot.guild_service.get_configuration(operation.guild_id)
            channel_id = configuration.operations_channel_id if configuration else None
            if channel_id is None:
                await interaction.followup.send(
                    "⚠️ No operations channel configured — run `/unit setup` first.",
                    ephemeral=True,
                )
                return
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            mission = await bot.mission_service.get_mission(operation.mission_id) if bot.mission_service else None  # type: ignore[union-attr]

            notes: list[str] = []
            try:
                # 1) The briefing goes in first, directly above the signup post.
                await self._post_brief(channel, operation, notes)
                # 2) Then the operation post with the attendance UI.
                operation.status = "open"  # provisional look; persisted below
                message = await channel.send(  # type: ignore[union-attr]
                    embed=embeds.operation_embed(operation, mission, Roster([], [], [], [])),
                    view=operation_post_view(operation),
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    f"⚠️ I can't post in <#{channel_id}> — fix my channel permissions and retry.",
                    ephemeral=True,
                )
                return
            await bot.operation_service.mark_published(
                self._operation_id, channel.id, message.id
            )
            self.stop()
            suffix = ("\n" + "\n".join(notes)) if notes else ""
            await interaction.followup.send(
                f"📣 Operation published — signups are open: {message.jump_url}{suffix}",
                ephemeral=True,
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _post_brief(self, channel, operation, notes: list[str]) -> None:
        """Post the pretty briefing (and any mission images) above the signup post."""
        bot = self._bot
        if bot.mission_service is None:
            return
        brief_groups: list[list[discord.Embed]] = []
        try:
            content = await bot.mission_service.get_brief(operation.mission_id)
            brief_groups = group_embeds(embeds.brief_embeds(operation.name, content))
        except AppError:
            notes.append("⚠️ Briefing could not be fetched — post it manually if needed.")
        files: list[discord.File] = []
        try:
            files = [
                discord.File(io.BytesIO(data), filename=filename)
                for filename, data in await bot.mission_service.get_attachments(
                    operation.mission_id
                )
            ]
        except AppError:
            notes.append("⚠️ Mission images could not be fetched.")

        for index, batch in enumerate(brief_groups):
            last = index == len(brief_groups) - 1
            await channel.send(embeds=batch, files=files if last else [])
            if last:
                files = []
        if files:  # images but no readable brief
            await channel.send(files=files)

    @discord.ui.button(label="Discard", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def discard(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await self._bot.operation_service.discard_unpublished(self._operation_id)
            self.stop()
            await interaction.response.edit_message(
                content="🗑️ Operation discarded.", embed=None, view=None
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)
