"""Operation commands.

Member surface: /operations (upcoming + drill in) · /operation view
Maker surface:  /operation create (guided modal flow)
Staff surface:  /operation manage (interactive panel)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.bot import embeds
from app.bot.permissions import PermissionLevel, require
from app.bot.views.components import operation_post_view, respond_error
from app.bot.views.manage import OperationPickView
from app.bot.views.operation_create import start_schedule_flow
from app.database.models.operation import Operation

if TYPE_CHECKING:
    from app.bot.bot import UnitBot


async def _send_operation_detail(
    bot: "UnitBot", interaction: discord.Interaction, operation: Operation
) -> None:
    """Ephemeral operation card — includes the live attendance buttons."""
    roster = await bot.operation_service.roster(operation.id)
    mission = None
    if bot.mission_service is not None:
        mission = await bot.mission_service.get_mission(operation.mission_id)
    content = None
    if operation.channel_id and operation.message_id:
        content = (
            "📌 Official post: https://discord.com/channels/"
            f"{operation.guild_id}/{operation.channel_id}/{operation.message_id}"
        )
    await interaction.followup.send(
        content,
        embed=embeds.operation_embed(operation, mission, roster),
        view=operation_post_view(operation),
        ephemeral=True,
    )


class OperationBrowseView(discord.ui.View):
    def __init__(self, bot: "UnitBot", operations: list[Operation]) -> None:
        super().__init__(timeout=600)
        self._bot = bot
        select = discord.ui.Select(
            placeholder="View an operation…",
            options=[
                discord.SelectOption(
                    label=f"{op.name} ({op.mission_id})"[:100],
                    value=str(op.id),
                    description=f"{op.status} · {op.scheduled_at:%d %b %Y %H:%M} UTC"[:100],
                )
                for op in operations[:25]
            ],
        )
        select.callback = self._on_pick  # type: ignore[method-assign]
        self._select = select
        self.add_item(select)

    async def _on_pick(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            operation = await self._bot.operation_service.get(int(self._select.values[0]))
            await _send_operation_detail(self._bot, interaction, operation)
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class OperationsCog(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot

    async def _operation_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        try:
            if interaction.guild is None:
                return []
            operations = await self.bot.operation_service.list_upcoming(interaction.guild.id)
        except Exception:  # autocomplete must never raise
            return []
        needle = current.strip().lower()
        choices = [
            app_commands.Choice(
                name=f"{op.name} · {op.scheduled_at:%d %b %H:%M} UTC"[:100], value=op.id
            )
            for op in operations
            if not needle or needle in op.name.lower() or needle in op.mission_id.lower()
        ]
        return choices[:25]

    @app_commands.command(name="operations", description="Upcoming operations")
    @app_commands.guild_only()
    @require(PermissionLevel.MEMBER)
    async def operations(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        assert interaction.guild is not None
        upcoming = await self.bot.operation_service.list_upcoming(interaction.guild.id)
        visible = [op for op in upcoming if op.message_id is not None or op.status != "scheduled"]
        if not visible:
            await interaction.followup.send(
                "📭 No operations scheduled right now. Check back soon!"
            )
            return
        description = "\n\n".join(embeds.operation_line(op) for op in visible[:10])
        embed = discord.Embed(
            title=f"🎯 Upcoming operations ({len(visible)})",
            description=description,
            colour=embeds.BLURPLE,
        )
        await interaction.followup.send(embed=embed, view=OperationBrowseView(self.bot, visible))

    operation = app_commands.Group(
        name="operation", description="Operation details and management", guild_only=True
    )

    @operation.command(name="view", description="One operation with attendance")
    @app_commands.describe(operation_id="Operation — start typing to search")
    @app_commands.rename(operation_id="operation")
    @app_commands.autocomplete(operation_id=_operation_autocomplete)
    @require(PermissionLevel.MEMBER)
    async def operation_view(self, interaction: discord.Interaction, operation_id: int) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        operation = await self.bot.operation_service.get(operation_id)
        await _send_operation_detail(self.bot, interaction, operation)

    @operation.command(name="create", description="Schedule a mission as an operation")
    @app_commands.describe(mission_id="Mission to schedule (optional — a picker opens otherwise)")
    @app_commands.rename(mission_id="mission")
    @require(PermissionLevel.MISSION_MAKER)
    async def operation_create(
        self, interaction: discord.Interaction, mission_id: str | None = None
    ) -> None:
        # No defer: the flow may open a modal, which must be the first response.
        await start_schedule_flow(interaction, mission_id)

    @operation_create.autocomplete("mission_id")
    async def _create_mission_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            service = self.bot.mission_service
            if service is None:
                return []
            entries = await (service.search(current) if current.strip() else service.list_missions())
        except Exception:
            return []
        return [
            app_commands.Choice(
                name=f"{entry.mission_id} — {entry.name}"[:100], value=entry.mission_id
            )
            for entry in entries
            if entry.status != "archived"
        ][:25]

    @operation.command(name="manage", description="Staff: lock, reschedule, complete or cancel")
    @require(PermissionLevel.STAFF)
    async def operation_manage(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        assert interaction.guild is not None
        upcoming = await self.bot.operation_service.list_upcoming(interaction.guild.id)
        if not upcoming:
            await interaction.followup.send("📭 No manageable operations.", ephemeral=True)
            return
        await interaction.followup.send(
            "⚙️ **Manage operations** — pick one:",
            view=OperationPickView(self.bot, upcoming),
            ephemeral=True,
        )


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(OperationsCog(bot))
