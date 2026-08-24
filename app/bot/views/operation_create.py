"""Guided operation scheduling — zero typing.

Flow: pick mission → pick date / hour / minute from select menus → preview →
publish. The operation name comes straight from the mission file on GitHub.
Publishing posts the formatted briefing (+ images) to the briefing channel
and the signup post to the attendance channel, then announces it.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Awaitable, Callable
from zoneinfo import ZoneInfo

import discord

from app.bot import embeds
from app.bot.operation_messages import announce_operation, post_briefing
from app.bot.views.components import operation_post_view, respond_error
from app.database.models.mission import MissionIndexEntry
from app.errors import AppError, MissionNotFoundError, MissionsNotConfiguredError, ValidationError
from app.services.operations import Roster

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)

_DAYS_AHEAD = 25  # Discord select menus allow max 25 options
_MINUTE_OPTIONS = ("00", "15", "30", "45")


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


class DateTimePickerView(discord.ui.View):
    """Date + time selection via select menus (Discord has no calendar
    widget for bots, so this is the no-typing equivalent)."""

    def __init__(
        self,
        tz_name: str,
        on_confirm: Callable[[discord.Interaction, datetime], Awaitable[None]],
        *,
        confirm_label: str = "Confirm date & time",
    ) -> None:
        super().__init__(timeout=600)
        self._tz = ZoneInfo(tz_name)
        self._tz_name = tz_name
        self._on_confirm = on_confirm
        self._date: date | None = None
        self._hour: int | None = None
        self._minute: int | None = None

        today = datetime.now(self._tz).date()
        date_select = discord.ui.Select(
            placeholder="📅 Pick the day…",
            options=[
                discord.SelectOption(
                    label=(today + timedelta(days=offset)).strftime("%A %d %B"),
                    value=(today + timedelta(days=offset)).isoformat(),
                    description="today" if offset == 0 else None,
                )
                for offset in range(_DAYS_AHEAD)
            ],
            row=0,
        )
        date_select.callback = self._on_date  # type: ignore[method-assign]
        self._date_select = date_select
        self.add_item(date_select)

        hour_select = discord.ui.Select(
            placeholder=f"🕗 Pick the hour ({tz_name})…",
            options=[
                discord.SelectOption(label=f"{hour:02d}:00 – {hour:02d}:59", value=str(hour))
                for hour in range(24)
            ],
            row=1,
        )
        hour_select.callback = self._on_hour  # type: ignore[method-assign]
        self._hour_select = hour_select
        self.add_item(hour_select)

        minute_select = discord.ui.Select(
            placeholder="⏱️ Pick the minutes…",
            options=[discord.SelectOption(label=f":{m}", value=m) for m in _MINUTE_OPTIONS],
            row=2,
        )
        minute_select.callback = self._on_minute  # type: ignore[method-assign]
        self._minute_select = minute_select
        self.add_item(minute_select)

        confirm = discord.ui.Button(
            label=confirm_label, emoji="✅", style=discord.ButtonStyle.success, row=3
        )
        confirm.callback = self._confirm  # type: ignore[method-assign]
        self.add_item(confirm)

    async def _on_date(self, interaction: discord.Interaction) -> None:
        self._date = date.fromisoformat(self._date_select.values[0])
        await interaction.response.defer()

    async def _on_hour(self, interaction: discord.Interaction) -> None:
        self._hour = int(self._hour_select.values[0])
        await interaction.response.defer()

    async def _on_minute(self, interaction: discord.Interaction) -> None:
        self._minute = int(self._minute_select.values[0])
        await interaction.response.defer()

    async def _confirm(self, interaction: discord.Interaction) -> None:
        try:
            missing = [
                label
                for label, value in (
                    ("day", self._date), ("hour", self._hour), ("minutes", self._minute)
                )
                if value is None
            ]
            if missing:
                await interaction.response.send_message(
                    f"⚠️ Still missing: **{', '.join(missing)}** — pick from the menus above.",
                    ephemeral=True,
                )
                return
            local = datetime(
                self._date.year, self._date.month, self._date.day,
                self._hour, self._minute, tzinfo=self._tz,
            )
            when_utc = local.astimezone(timezone.utc)
            if when_utc <= datetime.now(timezone.utc):
                await interaction.response.send_message(
                    "⚠️ That time is in the past — pick a future time.", ephemeral=True
                )
                return
            self.stop()
            await self._on_confirm(interaction, when_utc)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


async def start_schedule_flow(
    interaction: discord.Interaction, mission_id: str | None = None
) -> None:
    """First response: mission picker (or straight to the date picker)."""
    bot: "UnitBot" = interaction.client  # type: ignore[assignment]
    if bot.mission_service is None:
        raise MissionsNotConfiguredError()
    assert interaction.guild is not None
    tz_name = await _guild_timezone(bot, interaction.guild)

    if mission_id is not None:
        entry = await bot.mission_service.get_mission(mission_id)
        if entry is None:
            raise MissionNotFoundError(mission_id)
        await _send_datetime_picker(interaction, bot, entry, tz_name)
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


async def _send_datetime_picker(
    interaction: discord.Interaction, bot: "UnitBot", entry: MissionIndexEntry, tz_name: str
) -> None:
    async def on_confirm(picker_interaction: discord.Interaction, when_utc: datetime) -> None:
        await _create_and_preview(picker_interaction, bot, entry, tz_name, when_utc)

    content = (
        f"**Scheduling {entry.mission_id} — {entry.name}**\n"
        f"Pick the day and start time (unit timezone: **{tz_name}**):"
    )
    view = DateTimePickerView(tz_name, on_confirm)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=content, view=view, embed=None)
    else:
        await interaction.response.send_message(content, view=view, ephemeral=True)


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
            await interaction.response.defer()
            await _send_datetime_picker(interaction, self._bot, entry, self._tz_name)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


async def _create_and_preview(
    interaction: discord.Interaction,
    bot: "UnitBot",
    entry: MissionIndexEntry,
    tz_name: str,
    when_utc: datetime,
) -> None:
    try:
        await interaction.response.defer(ephemeral=True)
        objectives_text = None
        try:
            objectives = await bot.mission_service.get_objectives(entry.mission_id)  # type: ignore[union-attr]
            objectives_text = embeds.render_objectives(objectives)
        except AppError:
            pass  # operation still schedulable without the objectives block

        # The operation name comes straight from the mission file.
        operation = await bot.operation_service.create_operation(
            guild_id=interaction.guild.id,  # type: ignore[union-attr]
            mission_id=entry.mission_id,
            mission_name=entry.name,
            mission_status=entry.status,
            scheduled_at_utc=when_utc,
            tz_name=tz_name,
            created_by=interaction.user.id,
        )
        if objectives_text:
            operation = await bot.operation_service.set_objectives_snapshot(
                operation.id, objectives_text
            )

        preview = embeds.operation_embed(operation, entry, Roster([], [], [], []))
        configuration = await bot.guild_service.get_configuration(interaction.guild.id)  # type: ignore[union-attr]
        att = configuration.attendance_channel_id if configuration else None
        brief = configuration.briefing_channel_id if configuration else None
        if att and brief:
            hint = f"Preview — briefing goes to <#{brief}>, signups to <#{att}>. Publish?"
        else:
            hint = (
                "Preview — ⚠️ **attendance/briefing channels not configured** "
                "(`/unit setup` → create recommended channels), then press Publish."
            )
        await interaction.edit_original_response(
            content=hint,
            embed=preview,
            view=PublishOperationView(bot, operation.id),
        )
    except Exception as error:  # noqa: BLE001
        await respond_error(interaction, error)


class PublishOperationView(discord.ui.View):
    def __init__(self, bot: "UnitBot", operation_id: int) -> None:
        super().__init__(timeout=900)
        self._bot = bot
        self._operation_id = operation_id

    @discord.ui.button(label="Publish", emoji="📣", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            bot = self._bot
            operation = await bot.operation_service.get(self._operation_id)
            configuration = await bot.guild_service.get_configuration(operation.guild_id)
            attendance_id = configuration.attendance_channel_id if configuration else None
            briefing_id = configuration.briefing_channel_id if configuration else None
            if attendance_id is None or briefing_id is None:
                await interaction.followup.send(
                    "⚠️ The **Attendance** and **Operation brief** channels aren't "
                    "configured — run `/unit setup` (it can create them for you).",
                    ephemeral=True,
                )
                return
            attendance_channel = bot.get_channel(attendance_id) or await bot.fetch_channel(
                attendance_id
            )
            briefing_channel = bot.get_channel(briefing_id) or await bot.fetch_channel(
                briefing_id
            )
            mission = await bot.mission_service.get_mission(operation.mission_id) if bot.mission_service else None  # type: ignore[union-attr]

            try:
                # 1) Briefing (+ images) into the briefing channel.
                brief_ids = await post_briefing(bot, briefing_channel, operation)
                # 2) Signup post into the attendance channel.
                operation.status = "open"  # provisional look; persisted below
                message = await attendance_channel.send(  # type: ignore[union-attr]
                    embed=embeds.operation_embed(operation, mission, Roster([], [], [], [])),
                    view=operation_post_view(operation),
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "⚠️ I can't post in the attendance/briefing channels — "
                    "fix my permissions there and retry.",
                    ephemeral=True,
                )
                return
            operation = await bot.operation_service.mark_published(
                self._operation_id, attendance_channel.id, message.id
            )
            if brief_ids:
                await bot.operation_service.set_brief_messages(
                    self._operation_id, briefing_channel.id, brief_ids
                )
            # 3) Tell the unit.
            await announce_operation(bot, operation, "published")
            self.stop()
            await interaction.followup.send(
                f"📣 Operation published and announced — signups open: {message.jump_url}",
                ephemeral=True,
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

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
