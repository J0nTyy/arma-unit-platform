"""Mission commands.

Member surface:  /missions (browse + drill in)  ·  /mission view <id>
Maker surface:   /mission publish  (+ Validate/Publish/Schedule buttons on views)

Implementation details (sync, cache, index) are deliberately not visible
here — staff refresh the index with /unit sync.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.bot import embeds
from app.bot.permissions import PermissionLevel, require
from app.bot.views.components import mission_detail_view, respond_error
from app.bot.views.publish import continue_publish_flow
from app.database.models.mission import MissionIndexEntry
from app.errors import MissionNotFoundError, MissionsNotConfiguredError
from app.missions import MissionStatus
from app.services.missions import MissionService

if TYPE_CHECKING:
    from app.bot.bot import UnitBot

_MAX_LIST_ENTRIES = 15


class MissionBrowseView(discord.ui.View):
    """Select menu under /missions to open one mission's details."""

    def __init__(self, bot: "UnitBot", entries: list[MissionIndexEntry]) -> None:
        super().__init__(timeout=600)
        self._bot = bot
        select = discord.ui.Select(
            placeholder="View a mission in detail…",
            options=[
                discord.SelectOption(
                    label=f"{entry.mission_id} — {entry.name}"[:100],
                    value=entry.mission_id,
                    description=f"{entry.map_name} · {entry.mission_type} · {entry.status}"[:100],
                )
                for entry in entries[:25]
            ],
        )
        select.callback = self._on_pick  # type: ignore[method-assign]
        self._select = select
        self.add_item(select)

    async def _on_pick(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            mission_id = self._select.values[0]
            entry = await self._bot.mission_service.get_mission(mission_id)  # type: ignore[union-attr]
            if entry is None:
                raise MissionNotFoundError(mission_id)
            objectives = None
            try:
                objectives = await self._bot.mission_service.get_objectives(mission_id)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001 — details still render without objectives
                pass
            await interaction.followup.send(
                embed=embeds.mission_embed(entry, objectives),
                view=mission_detail_view(entry.mission_id),
                ephemeral=True,
            )
        except Exception as error:  # noqa: BLE001
            await respond_error(interaction, error)


class MissionsCog(commands.Cog):
    def __init__(self, bot: "UnitBot") -> None:
        self.bot = bot

    def _service(self) -> MissionService:
        service = self.bot.mission_service
        if service is None:
            raise MissionsNotConfiguredError()
        return service

    async def _mission_id_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            service = self._service()
            entries = await (
                service.search(current) if current.strip() else service.list_missions()
            )
        except Exception:  # autocomplete must never raise
            return []
        return [
            app_commands.Choice(
                name=f"{entry.mission_id} — {entry.name}"[:100], value=entry.mission_id
            )
            for entry in entries[:25]
        ]

    # --- member commands ---------------------------------------------------------

    @app_commands.command(name="missions", description="Browse the unit's missions")
    @app_commands.describe(
        search="Find missions by name, map, type, tag or maker",
        status="Only show missions with this status",
    )
    @app_commands.guild_only()
    @require(PermissionLevel.MEMBER)
    async def missions(
        self,
        interaction: discord.Interaction,
        search: str | None = None,
        status: MissionStatus | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        service = self._service()
        if search:
            entries = await service.search(search)
            if status:
                entries = [entry for entry in entries if entry.status == status.value]
        else:
            entries = await service.list_missions(status=status.value if status else None)

        if not entries:
            hint = "Try a different search." if search else "Ask staff to run `/unit sync`."
            await interaction.followup.send(f"📭 No missions found. {hint}")
            return

        shown = entries[:_MAX_LIST_ENTRIES]
        description = "\n\n".join(embeds.mission_line(entry) for entry in shown)
        if len(entries) > len(shown):
            description += f"\n\n… and {len(entries) - len(shown)} more — refine your search."
        title = f"🪖 Missions ({len(entries)})"
        if search:
            title += f" — “{search}”"
        if status:
            title += f" — {status.value}"
        embed = discord.Embed(title=title, description=description, colour=embeds.BLURPLE)
        await interaction.followup.send(embed=embed, view=MissionBrowseView(self.bot, shown))

    mission = app_commands.Group(
        name="mission", description="Mission details and publishing", guild_only=True
    )

    @mission.command(name="view", description="One mission in detail")
    @app_commands.describe(mission_id="Mission — start typing to search")
    @app_commands.rename(mission_id="mission")
    @app_commands.autocomplete(mission_id=_mission_id_autocomplete)
    @require(PermissionLevel.MEMBER)
    async def mission_view(self, interaction: discord.Interaction, mission_id: str) -> None:
        await interaction.response.defer(thinking=True)
        service = self._service()
        entry = await service.get_mission(mission_id)
        if entry is None:
            raise MissionNotFoundError(mission_id)
        objectives = None
        try:
            objectives = await service.get_objectives(entry.mission_id)
        except Exception:  # noqa: BLE001
            pass
        await interaction.followup.send(
            embed=embeds.mission_embed(entry, objectives),
            view=mission_detail_view(entry.mission_id),
        )

    # --- maker commands ------------------------------------------------------------

    @mission.command(name="publish", description="Post a mission to a Discord channel")
    @app_commands.describe(mission_id="Mission — start typing to search")
    @app_commands.rename(mission_id="mission")
    @app_commands.autocomplete(mission_id=_mission_id_autocomplete)
    @require(PermissionLevel.MISSION_MAKER)
    async def mission_publish(self, interaction: discord.Interaction, mission_id: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await continue_publish_flow(interaction, mission_id)


async def setup(bot: "UnitBot") -> None:
    await bot.add_cog(MissionsCog(bot))
