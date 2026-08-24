"""Staff attendance finalization panel.

Signups stay untouched; staff mark the authoritative verdict per member
(🟢 attended / 🔴 absent / 🟡 excused) — every change is audit-logged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from app.bot import embeds
from app.bot.permissions import PermissionLevel, ensure_level
from app.bot.views.components import respond_error
from app.database.models.operation import Operation
from app.database.models.player import FinalAttendance

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

log = logging.getLogger(__name__)

_FINAL_ICON = {"attended": "🟢", "absent": "🔴", "excused": "🟡", None: "▫️"}
_SIGNUP_LABEL = {
    "attending": "signed up", "waitlist": "waitlisted", "maybe": "maybe",
    "declined": "declined", None: "walk-on",
}


async def build_finalize_panel(bot: "UnitBot", operation: Operation):
    roster = await bot.attendance_service.finalization_roster(operation.id)
    lines = [
        f"{_FINAL_ICON.get(entry.final_status)} **{entry.display_name}** — "
        f"{_SIGNUP_LABEL.get(entry.signup_status)}"
        + (f" → *{entry.final_status}*" if entry.final_status else " → *pending*")
        for entry in roster[:40]
    ]
    pending = sum(1 for entry in roster if entry.final_status is None)
    embed = discord.Embed(
        title=f"📋 Attendance — {operation.name}",
        description=(
            f"<t:{embeds.unix_ts(operation.scheduled_at)}:F>\n\n" + "\n".join(lines)
            if lines else "Nobody signed up for this operation."
        ),
        colour=embeds.GREEN if pending == 0 else embeds.ORANGE,
    )
    embed.set_footer(
        text=f"{pending} pending · pick a member below, then press a verdict button"
    )
    return embed, FinalizePanelView(bot, operation, roster)


class OperationPickForAttendanceView(discord.ui.View):
    def __init__(self, bot: "UnitBot", operations: list[Operation]) -> None:
        super().__init__(timeout=600)
        self._bot = bot
        self._by_id = {str(op.id): op for op in operations[:25]}
        select = discord.ui.Select(
            placeholder="Select the operation to finalize…",
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
            operation = self._by_id[self._select.values[0]]
            embed, view = await build_finalize_panel(self._bot, operation)
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class FinalizePanelView(discord.ui.View):
    def __init__(self, bot: "UnitBot", operation: Operation, roster) -> None:
        super().__init__(timeout=900)
        self._bot = bot
        self._operation = operation
        self._selected: tuple[int, str] | None = None  # (user_id, display_name)

        if roster:
            member_select = discord.ui.Select(
                placeholder="Pick a member to mark…",
                options=[
                    discord.SelectOption(
                        label=entry.display_name[:100],
                        value=f"{entry.discord_user_id}:{entry.display_name[:80]}",
                        description=(
                            f"{_SIGNUP_LABEL.get(entry.signup_status)} · "
                            f"{entry.final_status or 'pending'}"
                        )[:100],
                    )
                    for entry in roster[:25]
                ],
                row=0,
            )
            member_select.callback = self._on_member  # type: ignore[method-assign]
            self._member_select = member_select
            self.add_item(member_select)

        walk_on = discord.ui.UserSelect(
            placeholder="➕ Add someone who wasn't signed up…", row=2
        )
        walk_on.callback = self._on_walk_on  # type: ignore[method-assign]
        self._walk_on = walk_on
        self.add_item(walk_on)

    async def _on_member(self, interaction: discord.Interaction) -> None:
        try:
            user_id, _, name = self._member_select.values[0].partition(":")
            self._selected = (int(user_id), name)
            await interaction.response.defer()
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _on_walk_on(self, interaction: discord.Interaction) -> None:
        try:
            user = self._walk_on.values[0]
            if user.bot:
                await interaction.response.send_message("🤖 That's a bot.", ephemeral=True)
                return
            display = getattr(user, "display_name", user.name)
            self._selected = (user.id, display)
            await interaction.response.send_message(
                f"Selected **{display}** — now press a verdict button.", ephemeral=True
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    async def _mark(self, interaction: discord.Interaction, status: FinalAttendance) -> None:
        await ensure_level(interaction, PermissionLevel.STAFF)
        if self._selected is None:
            await interaction.response.send_message(
                "⚠️ Pick a member from the dropdown first.", ephemeral=True
            )
            return
        user_id, display_name = self._selected
        await self._bot.attendance_service.set_final_status(
            self._operation.id, self._operation.guild_id, user_id, display_name,
            status, interaction.user.id,
        )
        operation = await self._bot.operation_service.get(self._operation.id)
        embed, view = await build_finalize_panel(self._bot, operation)
        view._selected = self._selected  # keep the selection for rapid marking
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Attended", emoji="🟢", style=discord.ButtonStyle.success, row=1)
    async def attended(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await self._mark(interaction, FinalAttendance.ATTENDED)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    @discord.ui.button(label="Absent", emoji="🔴", style=discord.ButtonStyle.danger, row=1)
    async def absent(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await self._mark(interaction, FinalAttendance.ABSENT)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    @discord.ui.button(label="Excused", emoji="🟡", style=discord.ButtonStyle.secondary, row=1)
    async def excused(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await self._mark(interaction, FinalAttendance.EXCUSED)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    @discord.ui.button(label="All signed-up → attended", emoji="✅",
                       style=discord.ButtonStyle.primary, row=3)
    async def bulk(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            await ensure_level(interaction, PermissionLevel.STAFF)
            written = await self._bot.attendance_service.finalize_all_signed_up(
                self._operation.id, self._operation.guild_id, interaction.user.id
            )
            operation = await self._bot.operation_service.get(self._operation.id)
            embed, view = await build_finalize_panel(self._bot, operation)
            await interaction.response.edit_message(embed=embed, view=view)
            await interaction.followup.send(
                f"✅ Marked {written} member(s) as attended.", ephemeral=True
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)

    @discord.ui.button(label="Done", emoji="✔️", style=discord.ButtonStyle.secondary, row=3)
    async def done(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(view=None)
