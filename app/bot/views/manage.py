"""Staff operation management panel: lock/open, complete, cancel, reschedule,
repost — all through one interactive ephemeral panel."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from app.bot import embeds
from app.bot.operation_messages import announce_operation
from app.bot.permissions import PermissionLevel, ensure_level
from app.bot.views.components import (
    operation_post_view,
    refresh_operation_message,
    respond_error,
)
from app.database.models.operation import Operation, OperationStatus

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)


def _panel_embed(operation: Operation) -> discord.Embed:
    badge = embeds.OPERATION_STATUS_BADGE.get(operation.status, operation.status)
    when = f"<t:{embeds.unix_ts(operation.scheduled_at)}:F>"
    embed = discord.Embed(
        title=f"⚙️ Manage — {operation.name}",
        description=(
            f"{badge}\n{when}\nMission `{operation.mission_id}` · "
            f"max {operation.max_players} players"
        ),
        colour=embeds.OPERATION_STATUS_COLOUR.get(operation.status, embeds.BLURPLE),
    )
    if operation.message_id and operation.channel_id:
        embed.add_field(
            name="Post",
            value=f"https://discord.com/channels/{operation.guild_id}/{operation.channel_id}/{operation.message_id}",
        )
    return embed


class OperationPickView(discord.ui.View):
    """Ephemeral picker shown by /operation manage."""

    def __init__(self, bot: "UnitBot", operations: list[Operation]) -> None:
        super().__init__(timeout=600)
        self._bot = bot
        self._by_id = {str(op.id): op for op in operations[:25]}
        select = discord.ui.Select(
            placeholder="Select an operation…",
            options=[
                discord.SelectOption(
                    label=f"{op.name} ({op.mission_id})"[:100],
                    value=str(op.id),
                    description=f"{op.status} · {op.scheduled_at:%d %b %Y %H:%M} UTC"[:100],
                )
                for op in self._by_id.values()
            ],
        )
        select.callback = self._on_pick  # type: ignore[method-assign]
        self._select = select
        self.add_item(select)

    async def _on_pick(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.STAFF)
            operation = await self._bot.operation_service.get(int(self._select.values[0]))
            await interaction.response.edit_message(
                content=None, embed=_panel_embed(operation),
                view=ManagePanelView(self._bot, operation),
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class ManagePanelView(discord.ui.View):
    def __init__(self, bot: "UnitBot", operation: Operation) -> None:
        super().__init__(timeout=600)
        self._bot = bot
        self._operation = operation
        status = operation.status
        self._add_button("🔒 Lock signups", self._lock, visible=status == "open")
        self._add_button("🔓 Reopen signups", self._reopen, visible=status == "locked")
        self._add_button("▶️ Mark active", self._activate, visible=status in ("open", "locked"))
        self._add_button("✅ Mark completed", self._complete, visible=status == "active")
        self._add_button("🕒 Reschedule", self._reschedule,
                         visible=status in ("scheduled", "open", "locked"))
        self._add_button("📣 Repost", self._repost, visible=status in ("open", "locked", "active"))
        self._add_button(
            "🔴 Cancel operation", self._cancel,
            visible=status not in ("completed", "cancelled"),
            style=discord.ButtonStyle.danger, row=2,
        )

    def _add_button(self, label, handler, *, visible, style=discord.ButtonStyle.secondary, row=1):
        if not visible:
            return
        button = discord.ui.Button(label=label, style=style, row=row)
        button.callback = handler  # type: ignore[method-assign]
        self.add_item(button)

    async def _apply(self, interaction: discord.Interaction, new_status: OperationStatus) -> None:
        await ensure_level(interaction, PermissionLevel.STAFF)
        await interaction.response.defer(ephemeral=True)
        operation = await self._bot.operation_service.transition(self._operation.id, new_status)
        await refresh_operation_message(self._bot, operation)
        await interaction.edit_original_response(
            embed=_panel_embed(operation), view=ManagePanelView(self._bot, operation)
        )

    async def _lock(self, interaction: discord.Interaction) -> None:
        try:
            await self._apply(interaction, OperationStatus.LOCKED)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _reopen(self, interaction: discord.Interaction) -> None:
        try:
            await self._apply(interaction, OperationStatus.OPEN)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _activate(self, interaction: discord.Interaction) -> None:
        try:
            await self._apply(interaction, OperationStatus.ACTIVE)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _complete(self, interaction: discord.Interaction) -> None:
        try:
            await self._apply(interaction, OperationStatus.COMPLETED)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _cancel(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.STAFF)
            await interaction.response.edit_message(
                content=f"Really cancel **{self._operation.name}**? "
                "Attendees will see the post marked cancelled.",
                embed=None,
                view=ConfirmCancelView(self._bot, self._operation),
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _reschedule(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.STAFF)
            await interaction.response.send_modal(RescheduleModal(self._bot, self._operation))
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _repost(self, interaction: discord.Interaction) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.STAFF)
            await interaction.response.defer(ephemeral=True)
            bot = self._bot
            operation = await bot.operation_service.get(self._operation.id)
            configuration = await bot.guild_service.get_configuration(operation.guild_id)
            channel_id = configuration.attendance_channel_id if configuration else None
            if channel_id is None:
                await interaction.followup.send(
                    "⚠️ No attendance channel configured (`/unit setup`).", ephemeral=True
                )
                return
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            mission = None
            if bot.mission_service is not None:
                mission = await bot.mission_service.get_mission(operation.mission_id)
            roster = await bot.operation_service.roster(operation.id)
            message = await channel.send(  # type: ignore[union-attr]
                embed=embeds.operation_embed(operation, mission, roster),
                view=operation_post_view(operation),
            )
            await bot.operation_service.set_message(operation.id, channel.id, message.id)
            await interaction.followup.send(f"📣 Reposted: {message.jump_url}", ephemeral=True)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class RescheduleModal(discord.ui.Modal):
    def __init__(self, bot: "UnitBot", operation: Operation) -> None:
        super().__init__(title=f"Reschedule {operation.name}"[:45])
        self._bot = bot
        self._operation = operation
        self.date_input = discord.ui.TextInput(
            label=f"New date (DD/MM/YYYY, {operation.timezone})"[:45], placeholder="05/09/2026"
        )
        self.time_input = discord.ui.TextInput(label="New time (24h HH:MM)", placeholder="20:00")
        self.add_item(self.date_input)
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            service = self._bot.operation_service
            when_utc = service.parse_local_datetime(
                self.date_input.value, self.time_input.value, self._operation.timezone
            )
            operation = await service.reschedule(self._operation.id, when_utc)
            await refresh_operation_message(self._bot, operation)
            await announce_operation(self._bot, operation, "rescheduled")
            unix = embeds.unix_ts(operation.scheduled_at)
            await interaction.followup.send(
                f"🕒 **{operation.name}** moved to <t:{unix}:F> and announced. "
                "Reminders were reset for the new time.",
                ephemeral=True,
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class ConfirmCancelView(discord.ui.View):
    def __init__(self, bot: "UnitBot", operation: Operation) -> None:
        super().__init__(timeout=120)
        self._bot = bot
        self._operation = operation

    @discord.ui.button(label="Yes, cancel it", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.STAFF)
            await interaction.response.defer(ephemeral=True)
            operation = await self._bot.operation_service.transition(
                self._operation.id, OperationStatus.CANCELLED
            )
            await refresh_operation_message(self._bot, operation)
            await announce_operation(self._bot, operation, "cancelled")
            await interaction.edit_original_response(
                content=f"🔴 **{operation.name}** cancelled and announced. The post moves "
                "to the operation logs in 24 hours.",
                view=None,
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    @discord.ui.button(label="No, keep it", style=discord.ButtonStyle.secondary)
    async def keep(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            operation = await self._bot.operation_service.get(self._operation.id)
            await interaction.response.edit_message(
                content=None, embed=_panel_embed(operation),
                view=ManagePanelView(self._bot, operation),
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


